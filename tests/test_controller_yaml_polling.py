"""Canonical orthogonal test suite for YamlStatePoller."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DOMAIN,
)
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import (
    AuthError,
    CannotConnect,
    InvalidHeaderError,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.helpers.template import Template
from homeassistant.helpers.update_coordinator import UpdateFailed


class DummyController:
    """Lightweight test controller stub."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize sterile controller stub."""
        self.debug = False
        self.name = "TestController"
        self.ip_address: str | None = "192.168.1.100"
        self.host: str | None = "192.168.1.100"
        self.available = True
        self.device_id = "XXXX"
        self.unique_id: str | None = "192.168.1.100"
        self.log_prefix = "[TestLog]"
        self.config: dict[str, Any] = {}
        self.token: str | None = "test_token"
        self.discovered_devices: list[Any] = []
        self._attributes: dict[str, Any] = {}
        self.hass: Any = MagicMock()
        self.loader: Any = MagicMock()
        self.loader.is_fully_initialized = True
        self.loader.operations = {}
        self.loader.properties = {}
        self.loader.sensors = {}
        self.loader._parsed_yaml_cache = {}
        self.loader.state_getter = MagicMock(value={})
        self.loader.state_getter.async_update_state = AsyncMock()
        self.loader.connection = None
        for k, v in kwargs.items():
            setattr(self, k, v)

    def update_state_attributes(self, new_attrs: dict[str, Any]) -> None:
        """Update simulated state attributes."""
        self._attributes = new_attrs


def test_poller_init_and_properties() -> None:
    """Test initial attributes, getters, and state cache management."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    assert poller.controller is ctrl
    assert poller.pending_updates == {}
    assert poller.last_icmp_diagnostic is None

    # device_state & last_device_state
    poller._last_device_state = None
    assert poller.last_device_state is None
    assert poller.device_state == {}

    poller._last_device_state = {"power": "on"}
    assert poller.last_device_state == {"power": "on"}
    assert poller.device_state == {"power": "on"}

    # clear_state_cache & _clear_state_cache
    poller._cached_device_state = {"a": 1}
    poller._pure_network_state = {"b": 2}
    poller.clear_state_cache()
    assert poller._cached_device_state is None
    assert poller._last_device_state is None
    assert poller._pure_network_state is None

    # get_hass_attr_for_op_id
    assert poller.get_hass_attr_for_op_id("hvac") == "hvac_mode"
    assert poller.get_hass_attr_for_op_id("target_temperature") == "target_temperature"
    assert poller.get_hass_attr_for_op_id("custom_op") == "custom_op"

    # is_property_superseded
    assert poller.is_property_superseded("target_temp", 22) is False
    poller.register_pending_update("target_temp", 24)
    assert poller.is_property_superseded("target_temp", 22) is True
    assert poller.is_property_superseded("target_temp", 24) is False

    # inject_optimistic_state with nested deepcopy verification
    prop = MagicMock(id="mode", connection_template=None)
    del prop.apply_optimistic_cascades
    del prop.set_device_state_for_values
    del prop.convert_hass_to_dev
    poller._get_state_node_from_prop = MagicMock(return_value="mode_node")

    st_getter_val: dict[str, Any] = {"mode_node": "cool", "nested": {"k": 1}}
    poller._pure_network_state = None
    poller.inject_optimistic_state(prop, "heat", st_getter_val)
    assert poller._pure_network_state == {"mode_node": "heat", "nested": {"k": 1}}
    assert st_getter_val == {"mode_node": "heat", "nested": {"k": 1}}
    st_getter_val["nested"]["k"] = 99
    assert poller._pure_network_state["nested"]["k"] == 1

    # _all_props execution
    ctrl.loader.state_getter = MagicMock()
    ctrl.loader.operations = {"op1": MagicMock()}
    ctrl.loader.sensors = {"s1": MagicMock()}
    all_p = poller._all_props()
    assert len(all_p) == 3


def test_pure_network_state_normalization() -> None:
    """Test full branch normalization for pure_network_state property."""
    poller = YamlStatePoller(DummyController())

    poller._pure_network_state = None
    assert poller.pure_network_state == {}

    poller._pure_network_state = {}
    assert poller.pure_network_state == {}

    poller._pure_network_state = ["not", "a", "dict"]  # type: ignore[assignment]
    assert poller.pure_network_state == {}

    poller._pure_network_state = {"temp": 21, "mode": "cool"}
    assert poller.pure_network_state == {"temp": 21, "mode": "cool"}

    poller._pure_network_state = {
        "Devices": [{"id": "0", "power": "on"}, {"id": "1", "power": "off"}]
    }
    assert poller.pure_network_state == {"id": "0", "power": "on"}

    poller._pure_network_state = {"Devices": []}
    assert poller.pure_network_state == {"Devices": []}

    poller._pure_network_state = {"Devices": "invalid"}
    assert poller.pure_network_state == {"Devices": "invalid"}

    poller._pure_network_state = {"Devices": ["invalid_string"]}
    assert poller.pure_network_state == {"Devices": ["invalid_string"]}


def test_pending_updates_lifecycle() -> None:
    """Test register and instant clear of anti-flicker pending updates."""
    poller = YamlStatePoller(DummyController())
    poller.register_pending_update("target_temp", 22)
    assert "target_temp" in poller.pending_updates
    assert poller.pending_updates["target_temp"][0] == 22

    poller.clear_pending_updates(["target_temp"])
    assert "target_temp" not in poller.pending_updates

    poller.clear_pending_updates(["non_existent_key"])


def test_values_match_and_prop_helpers() -> None:
    """Test value matching logic and property getters/setters."""
    assert YamlStatePoller._values_match("22", 22.0) is True
    assert YamlStatePoller._values_match(22.0, "22") is True
    assert YamlStatePoller._values_match("22.0", "22") is True
    assert YamlStatePoller._values_match("22.5", 22.0) is False
    assert YamlStatePoller._values_match("Cool", "cool") is True
    assert YamlStatePoller._values_match("Cool", "heat") is False
    assert YamlStatePoller._values_match(None, None) is True
    assert YamlStatePoller._values_match(None, "foo") is False
    assert YamlStatePoller._values_match("foo", None) is False

    class DummyEnum:
        value = "Cool"

    assert YamlStatePoller._values_match(DummyEnum(), "cool") is True
    assert YamlStatePoller._values_match("cool", DummyEnum()) is True

    d1 = {"value": 1}
    d2 = {"value": 2}
    assert YamlStatePoller._values_match(d1, d1) is True
    assert YamlStatePoller._values_match(d1, d2) is False

    class PropWithValue:
        value = "initial"

    class PropWithPrivateValue:
        _value = "initial_priv"

    p1 = PropWithValue()
    assert YamlStatePoller._get_prop_value(p1) == "initial"
    YamlStatePoller._set_prop_value(p1, "new_val")
    assert p1.value == "new_val"

    p2 = PropWithPrivateValue()
    assert YamlStatePoller._get_prop_value(p2) == "initial_priv"
    YamlStatePoller._set_prop_value(p2, "new_priv")
    assert p2._value == "new_priv"

    assert YamlStatePoller._get_prop_value(object()) is None


def test_get_state_node_from_prop_and_paths() -> None:
    """Test resolving state node keys and setting values by dot-notation paths."""
    poller = YamlStatePoller(DummyController())

    assert poller._get_state_node_from_prop(MagicMock(id=None)) is None

    p_node = MagicMock(id="p1", state_node="Device.Temp")
    assert poller._get_state_node_from_prop(p_node) == "Device.Temp"
    assert poller._get_state_node_from_prop(p_node) == "Device.Temp"

    p_priv_node = MagicMock(id="p2", state_node=None, _state_node="Device.Fan")
    assert poller._get_state_node_from_prop(p_priv_node) == "Device.Fan"

    tmpl_empty = MagicMock(template="")
    p_empty_tmpl = MagicMock(
        id="p3", state_node=None, _state_node=None, status_template=tmpl_empty
    )
    assert poller._get_state_node_from_prop(p_empty_tmpl) is None

    p_no_tmpl = MagicMock(
        id="p4", state_node=None, _state_node=None, status_template=None
    )
    assert poller._get_state_node_from_prop(p_no_tmpl) is None

    target: dict[str, Any] = {}
    poller._set_dict_value_by_path(target, "a.b.c", 10)
    assert target == {"a": {"b": {"c": 10}}}

    # Existing intermediate dict preserved (kills 'or current[part] is not None')
    target_existing: dict[str, Any] = {"a": {"keep": 1}}
    poller._set_dict_value_by_path(target_existing, "a.add", 2)
    assert target_existing == {"a": {"keep": 1, "add": 2}}

    target_list: dict[str, Any] = {}
    poller._set_dict_value_by_path(target_list, "items.0.name", "first")
    assert target_list == {"items": [{"name": "first"}]}

    poller._set_dict_value_by_path(target_list, "items.0.tags.1", "tag2")
    assert target_list["items"][0]["tags"] == [None, "tag2"]

    target_sparse: dict[str, Any] = {"items": [None]}
    poller._set_dict_value_by_path(target_sparse, "items.0.sub", "val")
    assert target_sparse["items"][0] == {"sub": "val"}

    with pytest.raises(
        ValueError, match="Path '.*' attempted to inflate list beyond limit"
    ):
        poller._set_dict_value_by_path(
            {}, f"list.{poller.MAX_LIST_INFLATION_SIZE + 1}", "overflow"
        )

    with pytest.raises(
        ValueError, match="Path '.*' attempted to inflate list beyond limit"
    ):
        poller._set_dict_value_by_path(
            {}, f"list.{poller.MAX_LIST_INFLATION_SIZE + 1}.sub", "overflow"
        )

    poller._set_dict_value_by_path(
        {"items": ["string"]}, "items.not_a_digit.sub", "val"
    )


def test_inject_value_into_state_all_paths() -> None:
    """Test value injection into device states with converters and connection templates."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    poller._inject_value_into_state(MagicMock(), "not_a_dict", 123)

    prop = MagicMock(id="temp")
    prop.convert_hass_to_dev.return_value = 24.0
    poller._get_state_node_from_prop = MagicMock(return_value="target_temp")
    state: dict[str, Any] = {}
    poller._inject_value_into_state(prop, state, 24)
    assert state["target_temp"] == 24.0

    prop.convert_hass_to_dev.side_effect = Exception("Convert error")
    state2: dict[str, Any] = {}
    poller._inject_value_into_state(prop, state2, 24)
    assert state2["target_temp"] == 24

    prop_tmpl = MagicMock(id="sleep")
    del prop_tmpl.convert_hass_to_dev
    del prop_tmpl.apply_optimistic_cascades
    del prop_tmpl.set_device_state_for_values
    poller._get_state_node_from_prop = MagicMock(return_value="sleep_mode")

    prop_tmpl.connection_template = '{"json": {"options": ["Sleep_5"]}}'
    st_tmpl: dict[str, Any] = {}
    poller._inject_value_into_state(prop_tmpl, st_tmpl, 5)
    assert st_tmpl["sleep_mode"] == "Sleep_5"

    # Connection template using device_state context (kills drop device_state arg mutant)
    prop_tmpl.connection_template = Template(
        '{"json": {"options": ["{{ device_state.prefix }}_{{ value }}"]}}',
        hass=MagicMock(data={}),
    )
    st_dev_ctx: dict[str, Any] = {"prefix": "DynamicSleep"}
    poller._inject_value_into_state(prop_tmpl, st_dev_ctx, 3)
    assert st_dev_ctx["sleep_mode"] == "DynamicSleep_3"

    prop_tmpl.connection_template = Template(
        '{"options": ["Direct_{{ value }}"]}', hass=MagicMock(data={})
    )
    st_direct: dict[str, Any] = {}
    poller._inject_value_into_state(prop_tmpl, st_direct, 3)
    assert st_direct["sleep_mode"] == "Direct_3"

    prop_tmpl.connection_template = '{"options": "StringVal"}'
    st_str: dict[str, Any] = {}
    poller._inject_value_into_state(prop_tmpl, st_str, 3)
    assert st_str["sleep_mode"] == 3

    prop_tmpl.connection_template = '{"options": [999]}'
    st_int: dict[str, Any] = {}
    poller._inject_value_into_state(prop_tmpl, st_int, 3)
    assert st_int["sleep_mode"] == 3

    prop_tmpl.connection_template = "dummy"
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.render_template",
        return_value=b'{"options": ["bytes"]}',
    ):
        st_bytes: dict[str, Any] = {}
        poller._inject_value_into_state(prop_tmpl, st_bytes, 7)
        assert st_bytes["sleep_mode"] == 7

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.render_template",
        return_value={"json": {"options": ["Dict_Option"]}},
    ):
        st_dict_rend: dict[str, Any] = {}
        poller._inject_value_into_state(prop_tmpl, st_dict_rend, 7)
        assert st_dict_rend["sleep_mode"] == "Dict_Option"

    prop_tmpl.connection_template = "not valid json"
    st_bad_json: dict[str, Any] = {}
    poller._inject_value_into_state(prop_tmpl, st_bad_json, 8)
    assert st_bad_json["sleep_mode"] == 8

    poller._get_state_node_from_prop = MagicMock(return_value="")
    st_falsy: dict[str, Any] = {"x": 1}
    poller._inject_value_into_state(prop_tmpl, st_falsy, 9)
    assert st_falsy == {"x": 1}

    poller._get_state_node_from_prop = MagicMock(return_value=None)
    poller._inject_value_into_state(prop_tmpl, st_falsy, 9)
    assert st_falsy == {"x": 1}

    poller._get_state_node_from_prop = MagicMock(return_value=123)
    poller._inject_value_into_state(prop_tmpl, st_falsy, 9)
    assert st_falsy == {"x": 1}

    prop.convert_hass_to_dev.side_effect = None
    poller._get_state_node_from_prop = MagicMock(return_value="temp")
    st_with_devs = {"Devices": [{"temp": 18, "id": "0"}], "temp": 18}
    poller._inject_value_into_state(prop, st_with_devs, 22)
    assert st_with_devs["temp"] == 24.0
    assert st_with_devs["Devices"][0]["temp"] == 24.0

    st_empty_devs = {"Devices": [], "temp": 18}
    poller._inject_value_into_state(prop, st_empty_devs, 22)
    assert st_empty_devs["temp"] == 24.0
    assert st_empty_devs["Devices"] == []

    st_nondict_devs = {"Devices": ["not_a_dict"], "temp": 18}
    poller._inject_value_into_state(prop, st_nondict_devs, 22)
    assert st_nondict_devs["temp"] == 24.0
    assert st_nondict_devs["Devices"] == ["not_a_dict"]

    prop_cascade = MagicMock(id="casc")
    prop_cascade.apply_optimistic_cascades.side_effect = Exception("Cascade error")
    poller._inject_value_into_state(prop_cascade, {"temp": 20}, 20)

    prop_cascade_ok = MagicMock(id="casc_ok")
    prop_cascade_ok.convert_hass_to_dev.return_value = 25
    casc_state = {"temp": 20}
    poller._inject_value_into_state(prop_cascade_ok, casc_state, 20)
    prop_cascade_ok.apply_optimistic_cascades.assert_called_once_with(
        casc_state, 20, 25
    )

    prop_set_state = MagicMock(id="set_st")
    del prop_set_state.convert_hass_to_dev
    del prop_set_state.apply_optimistic_cascades
    prop_set_state.set_device_state_for_values.side_effect = Exception(
        "Set state error"
    )
    poller._inject_value_into_state(prop_set_state, {"temp": 20}, 20)

    prop_set_ok = MagicMock(id="set_ok")
    del prop_set_ok.convert_hass_to_dev
    del prop_set_ok.apply_optimistic_cascades
    set_state = {"temp": 20}
    poller._inject_value_into_state(prop_set_ok, set_state, 20)
    prop_set_ok.set_device_state_for_values.assert_called_once_with(set_state)


def test_find_device_node_matrix() -> None:
    """Test device node lookup, extraction, and fallback handling."""
    ctrl = DummyController(device_id="0")
    poller = YamlStatePoller(ctrl)

    ctrl.loader._parsed_yaml_cache = {
        "0": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        },
        "1": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        },
        "99": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        },
        "XXXX": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        },
    }
    sample_payload = {
        "Devices": [
            {"id": "0", "val": 10},
            {"id": "1", "val": 20},
        ]
    }

    ctrl.device_id = "1"
    assert poller._find_device_node(sample_payload) == {"id": "1", "val": 20}

    # Subdevice extraction for both full_state and pure_state
    pure_payload = {
        "Devices": [
            {"id": "0", "val": 100},
            {"id": "1", "val": 200},
        ]
    }
    d, p = poller._extract_device_nodes(sample_payload, pure_payload)
    assert d == {"id": "1", "val": 20}
    assert p == {"id": "1", "val": 200}

    d_none, p_none = poller._extract_device_nodes(None, None)  # type: ignore[arg-type]
    assert d_none is None
    assert p_none is None

    ctrl.device_id = "0"
    assert poller._find_device_node(sample_payload) == {"id": "0", "val": 10}

    ctrl.device_id = "99"
    assert poller._find_device_node(sample_payload) == {"id": "0", "val": 10}

    del ctrl.device_id
    assert poller._find_device_node(sample_payload) == {"id": "0", "val": 10}

    assert poller._find_device_node(None) is None
    assert poller._find_device_node("invalid") is None

    ctrl.loader._parsed_yaml_cache = {}
    assert poller._find_device_node(sample_payload) == sample_payload

    ctrl.loader._parsed_yaml_cache = "not_a_dict"
    assert poller._find_device_node(sample_payload) == sample_payload

    ctrl.loader._parsed_yaml_cache = {
        "XXXX": {"device": {"identifiers": {"path_to_devices": ["Devices"]}}}
    }
    assert poller._find_device_node({"Devices": []}) == {"Devices": []}
    assert poller._find_device_node({"Devices": "str"}) == {"Devices": "str"}

    with patch.object(
        poller, "_find_device_node", side_effect=Exception("Extraction explosion")
    ):
        d_err, p_err = poller._extract_device_nodes(sample_payload, pure_payload)
        assert d_err == sample_payload
        assert p_err == pure_payload


def test_apply_anti_flicker_locks_comprehensive() -> None:
    """Test anti-flicker lock enforcement, temporal shield boundary, and evictions."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)
    now = 100.0

    # 1. Global eviction via should_evict_all_locks
    op_evict = MagicMock(id="power")
    op_evict.should_evict_all_locks.return_value = True
    poller._pending_updates = {"mode": ("cool", now)}
    poller._apply_anti_flicker_locks(
        [op_evict], {}, {}, is_prediction=False, changed_keys={"power"}
    )
    assert poller._pending_updates == {}
    op_evict.should_evict_all_locks.assert_called_once_with({}, {"power"})

    op_evict_err = MagicMock(id="power_err")
    op_evict_err.should_evict_all_locks.side_effect = Exception("Eviction crash")
    poller._pending_updates = {"mode": ("cool", now)}
    with patch("time.monotonic", return_value=now):
        poller._apply_anti_flicker_locks(
            [op_evict_err], {}, {}, is_prediction=False, changed_keys={"power"}
        )
    assert "mode" in poller._pending_updates

    # 2. Expired lock TTL and non-calc simple op when pure_device_to_process is truthy
    class SimpleOp:
        id = "simple_op"

    simple_op = SimpleOp()
    poller._get_state_node_from_prop = MagicMock(return_value="simple_node")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="simple_op")
    poller._pending_updates = {
        "expired": ("old", now - (poller.LOCK_TTL_SEC + 1.0)),
        "simple_op": ("fresh", now - 1.0),
    }
    dev_state: dict[str, Any] = {}
    with patch("time.monotonic", return_value=now):
        poller._apply_anti_flicker_locks(
            [simple_op], dev_state, {"pure": 1}, is_prediction=False, changed_keys=None
        )
    assert "expired" not in poller._pending_updates
    assert "simple_op" in poller._pending_updates
    assert dev_state["simple_node"] == "fresh"

    # 3. hass_attr != op_id mapping (kills 'if hass_attr == op_id')
    op_mapped = MagicMock(id="target_temperature_op")
    del op_mapped.should_evict_all_locks
    del op_mapped.convert_hass_to_dev
    op_mapped.calculate_value_from_state.return_value = 20
    poller._get_state_node_from_prop = MagicMock(return_value="target_temp_node")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="target_temperature")
    dev_mapped = {"target_temp_node": 20}
    poller._pending_updates = {"target_temperature": (22, 100.0)}
    with patch("time.monotonic", return_value=101.0):
        poller._apply_anti_flicker_locks(
            [op_mapped], dev_mapped, {"target_temp_node": 20}, False, None
        )
    assert dev_mapped["target_temp_node"] == 22

    # 4. Lock calculation exception handled gracefully
    op_calc_err = MagicMock(id="calc_err")
    del op_calc_err.should_evict_all_locks
    del op_calc_err.convert_hass_to_dev
    op_calc_err.calculate_value_from_state.side_effect = Exception("Calc crash")
    poller._pending_updates = {"calc_err": ("val", now - 5.0)}
    poller._get_state_node_from_prop = MagicMock(return_value="calc_node")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="calc_err")
    dev_state_calc: dict[str, Any] = {}
    with patch("time.monotonic", return_value=now):
        poller._apply_anti_flicker_locks(
            [op_calc_err],
            dev_state_calc,
            {"pure": 1},
            is_prediction=False,
            changed_keys=None,
        )
    assert "calc_err" in poller._pending_updates

    # 5. Temporal Shield exact boundary (LOCK_SHIELD_SEC = 3.0)
    op_shield = MagicMock(id="mode")
    del op_shield.should_evict_all_locks
    op_shield.calculate_value_from_state.return_value = "cool"
    poller._get_state_node_from_prop = MagicMock(return_value="mode_node")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="mode")

    with patch("time.monotonic", return_value=102.999):
        poller._pending_updates = {"mode": ("cool", 100.0)}
        poller._apply_anti_flicker_locks(
            [op_shield],
            {"mode_node": "cool"},
            {"mode_node": "cool"},
            False,
            None,
        )
        assert "mode" in poller._pending_updates

    with patch("time.monotonic", return_value=103.000):
        poller._pending_updates = {"mode": ("cool", 100.0)}
        poller._apply_anti_flicker_locks(
            [op_shield],
            {"mode_node": "cool"},
            {"mode_node": "cool"},
            False,
            None,
        )
        assert "mode" not in poller._pending_updates

    # Empty pure_device_to_process skips calculate_value_from_state (kills and->or mutant)
    op_shield.calculate_value_from_state.reset_mock()
    with patch("time.monotonic", return_value=105.0):
        poller._pending_updates = {"mode": ("cool", 100.0)}
        poller._apply_anti_flicker_locks(
            [op_shield], {"mode_node": "heat"}, {}, False, None
        )
    op_shield.calculate_value_from_state.assert_not_called()
    assert "mode" in poller._pending_updates

    # 6. changed_keys filter & push override when pure_val != pend_val
    with patch("time.monotonic", return_value=105.0):
        poller._pending_updates = {"mode": ("cool", 100.0)}
        poller._apply_anti_flicker_locks(
            [op_shield],
            {"mode_node": "cool"},
            {"mode_node": "cool"},
            False,
            changed_keys={"wind_node"},
        )
        assert "mode" in poller._pending_updates

    with patch("time.monotonic", return_value=106.0):
        poller._pending_updates = {"mode": ("heat", 100.0)}
        poller._apply_anti_flicker_locks(
            [op_shield],
            {"mode_node": "cool"},
            {"mode_node": "cool"},
            False,
            changed_keys={"mode_node"},
        )
        assert "mode" not in poller._pending_updates

    # 7. Strict eviction logic (Solo Killer 7)
    op1 = MagicMock(id="op1")
    op1.calculate_value_from_state.return_value = "v1_wrong"
    del op1.should_evict_all_locks
    op2 = MagicMock(id="op2")
    op2.calculate_value_from_state.return_value = "v2"
    del op2.should_evict_all_locks

    poller._get_state_node_from_prop = lambda op: "Key1" if op.id == "op1" else "Key2"
    poller._get_hass_attr_for_op_id = lambda op_id: op_id
    poller._pending_updates = {"op1": ("v1", 100.0), "op2": ("v2", 100.0)}
    with patch("time.monotonic", return_value=125.0):
        poller._apply_anti_flicker_locks(
            [op1, op2],
            {},
            {"Key2": "v2"},
            is_prediction=False,
            changed_keys={"Key2"},
        )
    assert "op1" in poller._pending_updates
    assert "op2" not in poller._pending_updates


def test_predict_dependency_cascades() -> None:
    """Test dependency cascade prediction and mutant continue/break safety."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    op1 = MagicMock(id="op1_invalid")
    op1.is_valid.return_value = False
    del op1.get_valid_values

    op2 = MagicMock(id="op2_valid")
    op2.is_valid.return_value = True
    del op2.get_valid_values
    op2.values = ["val_a", "val_b"]
    poller._get_prop_value = MagicMock(
        side_effect=lambda op: "invalid_val" if op.id == "op2_valid" else None
    )
    poller._get_state_node_from_prop = MagicMock(return_value="op2_node")

    ctrl.loader.operations = {"op1": op1, "op2": op2}

    corrections = poller._predict_dependency_cascades({})
    assert corrections == {"op2_valid": "val_a"}

    op3 = MagicMock(id="op3_dict")
    op3.is_valid.return_value = True
    op3.get_valid_values.return_value = ["v_valid"]
    poller._get_prop_value = MagicMock(return_value="v_invalid")
    ctrl.loader.operations = {"op3": op3}
    assert poller._predict_dependency_cascades({}) == {"op3_dict": "v_valid"}

    op4 = MagicMock(id="op4_dict_values")
    op4.is_valid.return_value = True
    del op4.get_valid_values
    op4.values = {"v_dict_1": "label", "v_dict_2": "label"}
    poller._get_prop_value = MagicMock(return_value="v_invalid")
    ctrl.loader.operations = {"op4": op4}
    assert poller._predict_dependency_cascades({}) == {"op4_dict_values": "v_dict_1"}


@pytest.mark.asyncio
async def test_async_update_properties_from_state_all_cases() -> None:
    """Test property update parsing, forensic logs, and lock enforcement."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    # 1. Uninitialized loader
    ctrl.loader.is_fully_initialized = False
    assert await poller.async_update_properties_from_state() == {}

    # 2. st_getter exists but value is None -> _extract_device_nodes not called
    ctrl.loader.is_fully_initialized = True
    ctrl.loader.state_getter = MagicMock(value=None)
    with patch.object(poller, "_extract_device_nodes") as mock_extract:
        assert await poller.async_update_properties_from_state() == {}
        mock_extract.assert_not_called()

    # 3. Default flags (is_prediction=False, force_update=False), explicit vs getter state
    prop_ok = MagicMock(id="prop_ok")
    prop_ok.async_update_state = AsyncMock()
    del prop_ok.state_attributes
    del prop_ok.get_valid_values
    del prop_ok.values
    ctrl.loader.operations = {"prop_ok": prop_ok}
    ctrl.loader.properties = {}
    ctrl.loader.sensors = {}
    ctrl.loader.state_getter.value = {"dev": 999}

    # full_device_state=None reads from state_getter.value
    await poller.async_update_properties_from_state()
    prop_ok.async_update_state.assert_awaited_once_with({"dev": 999}, False)
    assert poller.last_device_state == {"dev": 999}
    prop_ok.async_update_state.reset_mock()

    # Explicit full_device_state overrides state_getter.value and updates _last_device_state
    await poller.async_update_properties_from_state({"dev": 10})
    prop_ok.async_update_state.assert_awaited_once_with({"dev": 10}, False)
    assert poller.last_device_state == {"dev": 10}

    # Repeat call with identical state and default force_update=False -> early return
    prop_ok.async_update_state.reset_mock()
    assert await poller.async_update_properties_from_state({"dev": 10}) == {}
    prop_ok.async_update_state.assert_not_called()

    # force_update=True bypasses cache equality check
    await poller.async_update_properties_from_state({"dev": 10}, force_update=True)
    prop_ok.async_update_state.assert_awaited_once_with({"dev": 10}, False)

    # pending_updates bypasses cache equality check
    prop_ok.async_update_state.reset_mock()
    with patch("time.monotonic", return_value=100.0):
        poller._pending_updates = {"other": ("val", 100.0)}
        await poller.async_update_properties_from_state({"dev": 10})
    prop_ok.async_update_state.assert_awaited_once()

    # Subdevice routing via _extract_device_nodes passes full_device_state
    ctrl.device_id = "1"
    ctrl.loader._parsed_yaml_cache = {
        "1": {"device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}}
    }
    prop_ok.async_update_state.reset_mock()
    poller._pending_updates = {}
    await poller.async_update_properties_from_state(
        {"Devices": [{"id": "0", "v": 1}, {"id": "1", "v": 2}]}
    )
    prop_ok.async_update_state.assert_awaited_once_with({"id": "1", "v": 2}, False)
    assert poller.last_device_state == {"id": "1", "v": 2}
    ctrl.loader._parsed_yaml_cache = {}

    # 4. Forensic prediction logging guards
    ctrl.loader.operations = {}
    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling._LOGGER.debug"
        ) as mock_debug,
        patch("time.monotonic", return_value=100.0),
    ):
        poller._pending_updates = {"temp": (24, 100.0)}
        await poller.async_update_properties_from_state(
            {"dev": 2}, is_prediction=False, force_update=True
        )
        assert not any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        )
        assert not any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        )

        mock_debug.reset_mock()
        poller._pending_updates = {}
        await poller.async_update_properties_from_state({"dev": 2}, is_prediction=True)
        assert not any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        )
        assert not any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        )

        mock_debug.reset_mock()
        poller._pending_updates = {"temp": (24, 100.0)}
        await poller.async_update_properties_from_state({"dev": 2}, is_prediction=True)
        assert any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        )
        assert any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        )

        mock_debug.reset_mock()
        poller._pending_updates = {}
        with patch.object(
            poller, "_predict_dependency_cascades", return_value={"fan": "auto"}
        ):
            await poller.async_update_properties_from_state(
                {"dev": 2}, is_prediction=True
            )
        assert not any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        )
        assert any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        )

    # 5. Lock re-enforcement, hass_attr fallback (line 1045), and backup injection
    prop1 = MagicMock(id="op_main", value="old1")
    prop1.async_update_state = AsyncMock(side_effect=Exception("Async update error"))
    prop1.state_attributes = {"attr1": "val1"}
    del prop1.get_valid_values
    del prop1.values

    prop2 = MagicMock(id="op_alias", value="old2")
    prop2.async_update_state = AsyncMock()
    del prop2.state_attributes
    del prop2.get_valid_values
    del prop2.values

    prop3 = MagicMock(id="op_unlocked", value="keep_orig")
    prop3.async_update_state = AsyncMock()
    del prop3.state_attributes
    del prop3.get_valid_values
    del prop3.values

    ctrl.loader.operations = {
        "op_main": prop1,
        "op_alias": prop2,
        "op_unlocked": prop3,
    }

    poller._get_hass_attr_for_op_id = lambda op_id: (
        "target_temperature" if op_id == "op_alias" else op_id
    )
    with (
        patch("time.monotonic", return_value=100.0),
        patch.object(poller, "_inject_value_into_state") as mock_inject,
    ):
        poller._pending_updates = {
            "op_main": ("lock1", 100.0),
            "target_temperature": ("lock2", 100.0),
        }
        await poller.async_update_properties_from_state({"dev": 3}, force_update=True)
        # 2 calls per locked property: anti-flicker + exact backup injection args
        assert mock_inject.call_args_list == [
            call(prop1, {"dev": 3}, "lock1"),
            call(prop2, {"dev": 3}, "lock2"),
            call(prop1, {"dev": 3}, "lock1"),
            call(prop2, {"dev": 3}, "lock2"),
        ]

    assert prop1.value == "lock1"
    assert prop2.value == "lock2"
    assert prop3.value == "keep_orig"
    assert ctrl._attributes["attr1"] == "val1"
    assert "last_sync" in ctrl._attributes


@pytest.mark.asyncio
async def test_async_get_status() -> None:
    """Test status polling cache freshness TTL and memory state prioritizing."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    poller.async_update_state = AsyncMock(return_value={"power": "on"})
    poller._cached_device_state = {"power": "on"}
    poller._last_state_fetch_time = 100.0

    with patch("time.monotonic", return_value=102.0):
        await poller.async_get_status()
        poller.async_update_state.assert_called_once()

    poller.async_update_state.reset_mock()
    with patch("time.monotonic", return_value=101.99):
        ctrl.loader.state_getter.value = {"power": "on_ram"}
        res = await poller.async_get_status()
        assert res == {"power": "on_ram"}
        poller.async_update_state.assert_not_called()

        ctrl.loader.state_getter.value = None
        res_copy = await poller.async_get_status()
        assert res_copy == {"power": "on"}
        assert res_copy is not poller._cached_device_state


@pytest.mark.asyncio
async def test_async_merge_device_state() -> None:
    """Test partial state merge edge cases and atomic dictionary updates."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    assert await poller.async_merge_device_state({}) is False

    ctrl.loader = None
    assert await poller.async_merge_device_state({"k": "v"}) is False

    ctrl.loader = MagicMock(state_getter=None)
    assert await poller.async_merge_device_state({"k": "v"}) is False

    ctrl.loader.state_getter = MagicMock(value=None)
    poller._pure_network_state = None
    assert await poller.async_merge_device_state({"k": "v"}) is False

    poller._pure_network_state = {"existing": "data"}
    poller.async_update_properties_from_state = AsyncMock()
    assert await poller.async_merge_device_state({"new": "data"}) is True
    assert poller._pure_network_state == {"existing": "data", "new": "data"}
    poller.async_update_properties_from_state.assert_awaited_once_with(
        {"existing": "data", "new": "data"},
        force_update=True,
        changed_keys={"new"},
    )

    poller.async_update_properties_from_state.reset_mock()
    ctrl.loader.state_getter.value = {"base": 1}
    poller._pure_network_state = {}
    assert await poller.async_merge_device_state({"added": 2}) is True
    assert poller._pure_network_state == {"base": 1, "added": 2}
    assert ctrl.loader.state_getter.value == {"base": 1, "added": 2}
    poller.async_update_properties_from_state.assert_awaited_once_with(
        {"base": 1, "added": 2},
        force_update=True,
        changed_keys={"added"},
    )


@pytest.mark.asyncio
async def test_async_predict_and_correct_state() -> None:
    """Test command prediction, enum unwrapping, and cascade corrections."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    ctrl.loader.state_getter = None
    f1, c1 = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f1.value == 0 and c1 == {}

    ctrl.loader.state_getter = MagicMock(value=None)
    ctrl.loader.is_fully_initialized = False
    f2, c2 = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f2.value == 0 and c2 == {}

    ctrl.loader.is_fully_initialized = True
    f3, c3 = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f3.value == 0 and c3 == {}

    ctrl.loader.state_getter.value = {"mode": "cool"}
    ctrl.loader.operations = {}
    f4, c4 = await poller.async_predict_and_correct_state(
        MagicMock(), "missing_prop", "val"
    )
    assert f4.value == 0 and c4 == {}

    # Matching via _get_hass_attr_for_op_id (kills != mutant) + enum unwrapping
    class ModeEnum:
        value = "heat"

    other_op = MagicMock(id="other_op")
    fake_op = MagicMock(id="yaml_mode_op")
    fake_op.value = "cool"
    del fake_op.convert_hass_to_dev
    del fake_op.apply_optimistic_cascades
    del fake_op.set_device_state_for_values
    ctrl.loader.operations = {"other_op": other_op, "yaml_mode_op": fake_op}
    poller._get_state_node_from_prop = MagicMock(return_value="mode_node")
    poller._get_hass_attr_for_op_id = MagicMock(
        side_effect=lambda op_id: "hvac_mode" if op_id == "yaml_mode_op" else op_id
    )
    poller.async_update_properties_from_state = AsyncMock(return_value={"fan": "auto"})

    memory_state = {"mode_node": "cool"}
    ctrl.loader.state_getter.value = memory_state

    feat, corr = await poller.async_predict_and_correct_state(
        MagicMock(), "hvac_mode", ModeEnum()
    )
    assert feat.value == 0
    assert corr == {}
    assert fake_op.value == "heat"
    assert memory_state["mode_node"] == "heat"
    poller.async_update_properties_from_state.assert_awaited_once_with(
        memory_state, is_prediction=True
    )
    assert "hvac_mode" in poller.pending_updates
    assert "fan" in poller.pending_updates
    assert poller.pending_updates["fan"][0] == "auto"


@pytest.mark.asyncio
async def test_icmp_reachability_and_diagnostics() -> None:
    """Test ICMP ping reachability logic, diagnostic storage, and device filtering."""
    ctrl = DummyController(
        ip_address="192.168.1.50", config={CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    )
    poller = YamlStatePoller(ctrl)

    # Samsung 2878 skips ping (kills device_type = None mutant)
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        AsyncMock(return_value=True),
    ) as mock_ping_skip:
        await poller._async_perform_icmp_check()
        mock_ping_skip.assert_not_called()

    ctrl.config = {CONF_DEVICE_TYPE: "generic_ac"}
    ctrl.ip_address = None
    await poller._async_perform_icmp_check()
    assert poller.last_icmp_diagnostic is None

    ctrl.ip_address = "192.168.1.50"
    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
            AsyncMock(return_value=True),
        ) as mock_ping_ok,
        patch(
            "custom_components.climate_ip.controller_yaml_polling.get_last_network_diagnostic",
            return_value=None,
        ),
    ):
        await poller._async_perform_icmp_check()
        mock_ping_ok.assert_awaited_once_with("192.168.1.50", ctrl.log_prefix)
        assert poller.last_icmp_diagnostic is not None
        assert poller.last_icmp_diagnostic["is_reachable"] is True
        assert poller.last_icmp_diagnostic["status"] == "alive"

    existing_diag = {"is_reachable": True, "status": "alive", "rtt_ms": 1.5}
    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
            AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_polling.get_last_network_diagnostic",
            return_value=existing_diag,
        ),
    ):
        await poller._async_perform_icmp_check()
        assert poller.last_icmp_diagnostic == existing_diag

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
            AsyncMock(return_value=False),
        ),
        pytest.raises(CannotConnect, match=r"Host unreachable \(ICMP ping failed\)"),
    ):
        await poller._async_perform_icmp_check()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        AsyncMock(side_effect=Exception("ICMP crash")),
    ):
        await poller._async_perform_icmp_check()


@pytest.mark.asyncio
async def test_async_update_state_network_failures_and_repairs() -> None:
    """Test network failure resilience, cache fallbacks, repair issue lifecycle."""
    ctrl = DummyController(config={CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878})
    poller = YamlStatePoller(ctrl)

    ctrl.loader.state_getter = None
    assert await poller.async_update_state() is None

    # Normal success with 0 errors: no delete issue, deepcopy + cast check
    raw_nested = {"Devices": [{"sub": {"temp": 21}}]}
    ctrl.loader.state_getter = MagicMock()
    ctrl.loader.state_getter.async_update_state = AsyncMock(return_value=raw_nested)
    ctrl.loader.state_getter.value = raw_nested
    poller.async_update_properties_from_state = AsyncMock()
    poller._consecutive_connection_errors = 0

    def spy_cast(typ: Any, val: Any) -> Any:
        assert typ is not None
        return val

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
        ) as mock_del_zero,
        patch(
            "custom_components.climate_ip.controller_yaml_polling.cast",
            side_effect=spy_cast,
        ),
    ):
        res_ok = await poller.async_update_state()
        assert res_ok == raw_nested
        mock_del_zero.assert_not_called()
        ctrl.loader.state_getter.async_update_state.assert_called_with(None, False)
        poller.async_update_properties_from_state.assert_awaited_once_with(raw_nested)

    assert poller._pure_network_state is not None
    raw_nested["Devices"][0]["sub"]["temp"] = 99
    assert poller._pure_network_state["Devices"][0]["sub"]["temp"] == 21

    # "persistently offline" from 0 jumps directly to 2
    ctrl.loader.state_getter.async_update_state = AsyncMock(
        side_effect=CannotConnect("persistently offline")
    )
    poller._cached_device_state = {"power": "on"}
    poller._consecutive_connection_errors = 0
    res_po = await poller.async_update_state()
    assert res_po == {"power": "on"}
    assert poller._consecutive_connection_errors == 2

    # Generic error from 0 goes to 1
    ctrl.loader.state_getter.async_update_state.side_effect = CannotConnect(
        "Timeout HTTP"
    )
    poller._consecutive_connection_errors = 0
    res_g = await poller.async_update_state()
    assert res_g == {"power": "on"}
    assert poller._consecutive_connection_errors == 1

    # 3rd error triggers repair issue creation and raises UpdateFailed
    poller._consecutive_connection_errors = 2
    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_create_issue"
        ) as mock_issue,
        patch(
            "custom_components.climate_ip.controller_yaml_polling._LOGGER.info"
        ) as mock_info,
    ):
        with pytest.raises(UpdateFailed, match="Device unreachable: Timeout HTTP"):
            await poller.async_update_state()
        assert poller._consecutive_connection_errors == 3
        mock_issue.assert_called_once_with(
            ctrl.hass,
            DOMAIN,
            "device_offline_192_168_1_100",
            is_fixable=False,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key="connection_failed",
            translation_placeholders={
                "device_name": "Samsung AC 192.168.1.100",
                "host": "192.168.1.100",
                "ip_address": "192.168.1.100",
            },
        )
        mock_info.assert_called_once()
        assert poller._cached_device_state is None

    # Connection recovered
    poller._consecutive_connection_errors = 3
    ctrl.loader.state_getter.async_update_state.side_effect = None
    ctrl.loader.state_getter.async_update_state.return_value = {"power": "on"}
    ctrl.loader.state_getter.value = {"power": "on"}

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_del_issue:
        res_rec = await poller.async_update_state()
        assert res_rec == {"power": "on"}
        assert poller._consecutive_connection_errors == 0
        mock_del_issue.assert_called_once_with(
            ctrl.hass, DOMAIN, "device_offline_192_168_1_100"
        )

    # full_device_state is None
    ctrl.loader.state_getter.async_update_state.return_value = None
    poller._cached_device_state = {"cached": True}
    assert await poller.async_update_state() == {"cached": True}

    poller._cached_device_state = None
    with pytest.raises(UpdateFailed, match="Failed to get device state"):
        await poller.async_update_state()

    ctrl.loader.state_getter.async_update_state.side_effect = InvalidHeaderError(
        "Bad header"
    )
    with pytest.raises(InvalidHeaderError):
        await poller.async_update_state()

    # Repair issue fallback cascade (config name, host, ip_address, unknown)
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_create_issue"
    ) as mock_issue:
        ctrl.unique_id = None
        ctrl.host = None
        ctrl.ip_address = "10.0.0.10"
        ctrl.config = {"name": "Config Room"}
        poller._try_create_repair_issue()
        mock_issue.assert_called_with(
            ctrl.hass,
            DOMAIN,
            "device_offline_10_0_0_10",
            is_fixable=False,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key="connection_failed",
            translation_placeholders={
                "device_name": "Config Room",
                "host": "10.0.0.10",
                "ip_address": "10.0.0.10",
            },
        )

        mock_issue.reset_mock()
        ctrl.host = "host_only"
        ctrl.ip_address = None
        ctrl.config = {}
        poller._try_create_repair_issue()
        mock_issue.assert_called_with(
            ctrl.hass,
            DOMAIN,
            "device_offline_host_only",
            is_fixable=False,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key="connection_failed",
            translation_placeholders={
                "device_name": "Samsung AC host_only",
                "host": "host_only",
                "ip_address": "host_only",
            },
        )

        mock_issue.reset_mock()
        ctrl.host = None
        poller._try_create_repair_issue()
        mock_issue.assert_called_with(
            ctrl.hass,
            DOMAIN,
            "device_offline_unknown",
            is_fixable=False,
            is_persistent=False,
            severity=IssueSeverity.WARNING,
            translation_key="connection_failed",
            translation_placeholders={
                "device_name": "Samsung AC unknown",
                "host": "Unknown",
                "ip_address": "Unknown",
            },
        )

    ctrl.hass = None
    poller._try_create_repair_issue()
    poller._try_delete_repair_issue()

    ctrl.hass = MagicMock()
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_create_issue",
        side_effect=Exception("Issue err"),
    ):
        poller._try_create_repair_issue()
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue",
        side_effect=Exception("Delete err"),
    ):
        poller._try_delete_repair_issue()


@pytest.mark.asyncio
async def test_auth_refresh_flow() -> None:
    """Test SmartThings OAuth2 token refresh and connection dispatch."""
    ctrl = DummyController(config={CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878})
    poller = YamlStatePoller(ctrl)

    mock_entry = MagicMock()
    ctrl.hass.config_entries.async_entries.return_value = [mock_entry]

    mock_session = AsyncMock()
    mock_session.token = {"access_token": "new_refreshed_token"}

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.async_get_config_entry_implementation",
            AsyncMock(return_value="impl"),
        ) as mock_get_impl,
        patch(
            "custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_session,
        ) as mock_oauth_cls,
    ):
        token = await poller._refresh_smartthings_token()
        assert token == "new_refreshed_token"
        ctrl.hass.config_entries.async_entries.assert_called_with("smartthings")
        mock_get_impl.assert_awaited_once_with(ctrl.hass, mock_entry)
        mock_oauth_cls.assert_called_once_with(ctrl.hass, mock_entry, "impl")
        mock_session.async_ensure_token_valid.assert_awaited_once()

    ctrl.hass = None
    assert await poller._refresh_smartthings_token() is None

    ctrl.hass = MagicMock()
    ctrl.hass.config_entries.async_entries.return_value = []
    assert await poller._refresh_smartthings_token() is None

    ctrl.hass.config_entries.async_entries.return_value = [mock_entry]
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.config_entry_oauth2_flow.async_get_config_entry_implementation",
        AsyncMock(side_effect=Exception("OAuth error")),
    ):
        assert await poller._refresh_smartthings_token() is None

    ctrl.token = "old_token"
    ctrl.on_token_refreshed = MagicMock()
    ctrl.loader.state_getter.async_update_state = AsyncMock(
        side_effect=[AuthError("401"), {"status": "ok"}]
    )
    ctrl.loader.state_getter.value = {"status": "ok"}
    poller.async_update_properties_from_state = AsyncMock()

    conn = MagicMock()
    prop = MagicMock(get_connection=MagicMock(return_value=conn))
    ctrl.loader.operations = {"p1": prop, "p2": prop}
    ctrl.loader.properties = {}
    ctrl.loader.sensors = {}

    with patch.object(
        poller, "_refresh_smartthings_token", AsyncMock(return_value="new_token")
    ):
        res = await poller.async_update_state()
        assert res == {"status": "ok"}
        assert ctrl.token == "new_token"
        ctrl.on_token_refreshed.assert_called_once_with("new_token")
        conn.update_auth_token.assert_called_once_with("new_token")
        ctrl.loader.state_getter.async_update_state.assert_called_with(None, False)

    # on_token_refreshed = None must not raise AttributeError/TypeError (kills and->or)
    ctrl.on_token_refreshed = None
    ctrl.token = "old_token"
    ctrl.loader.state_getter.async_update_state = AsyncMock(
        side_effect=[AuthError("401"), {"status": "ok"}]
    )
    with patch.object(
        poller, "_refresh_smartthings_token", AsyncMock(return_value="new_token_2")
    ):
        assert await poller.async_update_state() == {"status": "ok"}

    ctrl.token = "old_token_again"
    ctrl.loader.state_getter.async_update_state = AsyncMock(
        side_effect=[AuthError("401"), Exception("Retry boom")]
    )
    with (
        patch.object(
            poller, "_refresh_smartthings_token", AsyncMock(return_value="retry_token")
        ),
        pytest.raises(UpdateFailed, match="Retry after token refresh failed"),
    ):
        await poller.async_update_state()

    ctrl.loader.state_getter.async_update_state = AsyncMock(
        side_effect=AuthError("401")
    )
    with (
        patch.object(
            poller, "_refresh_smartthings_token", AsyncMock(return_value=None)
        ),
        pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"),
    ):
        await poller.async_update_state()


@pytest.mark.asyncio
async def test_initial_device_discovery() -> None:
    """Test device node discovery for MIM-H03 and identifier resolution."""
    ctrl = DummyController(
        device_id="0", config={CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    )
    ctrl.loader.is_fully_initialized = False
    ctrl.loader.async_finish_initialization = AsyncMock()
    poller = YamlStatePoller(ctrl)
    poller.async_update_properties_from_state = AsyncMock()

    ctrl.loader._parsed_yaml_cache = {
        "0": {"device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}}
    }
    payload = {
        "Devices": [
            {"id": "0", "Mode": "IgnoreMe"},
            {"id": "dev_target", "Mode": "Cool"},
        ]
    }
    ctrl.loader.state_getter.async_update_state.return_value = payload
    ctrl.loader.state_getter.value = payload

    await poller.async_update_state()
    assert ctrl.device_id == "dev_target"
    ctrl.loader.async_finish_initialization.assert_called_once()

    # Configured non-"0" device_id must NOT be overwritten
    ctrl.device_id = "configured_id"
    ctrl.loader._parsed_yaml_cache = {
        "configured_id": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        }
    }
    await poller.async_update_state()
    assert ctrl.device_id == "configured_id"

    # Missing path_to_devices passes list fallback [] to get_value_by_path
    ctrl.loader._parsed_yaml_cache = {
        "configured_id": {"device": {"identifiers": {"dummy": "val"}}}
    }
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.get_value_by_path",
        return_value=None,
    ) as mock_get_path:
        await poller.async_update_state()
        assert isinstance(mock_get_path.call_args_list[0][0][1], list)

    assert poller._discover_target_node("other", [{"id": "1"}]) == {"id": "1"}
    assert poller._discover_target_node("other", []) is None
    assert poller._discover_target_node(DEVICE_TYPE_MIM_H03, [{"id": "0"}]) is None

    ctrl.loader.is_fully_initialized = False
    ctrl.loader._parsed_yaml_cache = MagicMock(
        get=MagicMock(side_effect=Exception("Discovery explosion"))
    )
    await poller.async_update_state()


@pytest.mark.asyncio
async def test_async_shutdown() -> None:
    """Test poller connection shutdown and exception handling."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)

    conn = AsyncMock()
    conn.stop_listening = AsyncMock(side_effect=Exception("Stop error"))
    conn.close = AsyncMock()
    ctrl.loader.connection = conn

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        AsyncMock(),
    ) as mock_sleep:
        await poller.async_shutdown()
        mock_sleep.assert_awaited_once_with(1.0)
        conn.stop_listening.assert_awaited_once()
        conn.close.assert_awaited_once()
        assert ctrl.loader.connection is None

    ctrl.loader.connection = None
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        AsyncMock(),
    ) as mock_sleep:
        await poller.async_shutdown()
        mock_sleep.assert_awaited_once_with(1.0)
