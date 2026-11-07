# pylint: disable=protected-access,too-few-public-methods,too-many-instance-attributes
"""Tests dedicated to annihilating surviving and untested mutants in YamlStatePoller."""

import time
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.climate_ip.const import DEVICE_TYPE_MIM_H03
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from homeassistant.helpers.template import Template


class NakedObj:
    """Sterile object without mock overhead to prevent side-effects."""

    def __init__(self, **kwargs):
        self.debug = False
        self.name = "TestName"
        self.ip_address = "1.2.3.4"
        self.available = True
        self.device_id = "XXXX"
        self.log_prefix = "TestLog"
        self.config = {}
        self.state_getter = None
        self.hass = MagicMock()
        self._attributes = {}
        self.__dict__.update(kwargs)

    def update_state_attributes(self, new_attrs):
        """Update simulated state attributes."""
        self._attributes = new_attrs


@pytest.mark.asyncio
async def test_mutant_deepcopy_async_get_status():
    """Verify shallow copy semantics in async_get_status & async_merge_device_state."""
    poller = YamlStatePoller(MagicMock())
    poller._last_state_fetch_time = time.monotonic()

    # 1. Test async_get_status shallow copy
    nested_state = {"nested": {"k": "safe"}}
    poller.controller.loader.state_getter = NakedObj(value=nested_state)
    poller._cached_device_state = nested_state

    res = await poller.async_get_status()
    # Shallow copy creates a distinct top-level dict reference
    assert res is not nested_state
    assert res == nested_state

    # 2. Test async_merge_device_state shallow copy
    poller._pure_network_state = {"nested_pure": {"k": "safe"}}
    poller.async_update_properties_from_state = AsyncMock()
    await poller.async_merge_device_state({"new": "data"})
    assert poller.controller.loader.state_getter.value is not poller._pure_network_state
    assert poller.controller.loader.state_getter.value["new"] == "data"


def test_mutant_discover_target_node_none_fallback():
    """KILLS: `next(..., None)` fallback removed in _discover_target_node."""
    poller = YamlStatePoller(MagicMock())
    devices = [{"id": "0", "Mode": "Cool"}, {"id": "1", "NoModeHere": "Yes"}]
    # None of these meet `id != "0" and "Mode" in d`. Should trigger `None` fallback safely.
    res = poller._discover_target_node(DEVICE_TYPE_MIM_H03, devices)
    assert res is None


@pytest.mark.asyncio
async def test_mutant_predict_and_correct_logic_flips():
    """KILLS: Boolean flips inside async_predict_and_correct_state."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # KILLS: `if not st_getter.value or not isinstance...` mutated to `and`
    poller.controller.loader.state_getter = NakedObj(value=None)
    feat, corr = await poller.async_predict_and_correct_state(None, "prop", "val")
    assert feat == 0
    assert corr == {}

    # Setup for successful flow
    poller.controller.loader.state_getter = NakedObj(value={"state": "ok"})
    poller.async_update_properties_from_state = AsyncMock(
        return_value={"other_prop": "v2"}
    )
    poller.register_pending_update = MagicMock()

    # KILLS: `if op_id == property_name or ...` mutated to `and`
    fake_op = MagicMock(id="not_the_prop")
    del fake_op.convert_hass_to_dev
    poller._get_state_node_from_prop = MagicMock(return_value="not_the_prop")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="target_prop")
    poller.controller.loader.operations = {"not_the_prop": fake_op}

    await poller.async_predict_and_correct_state(None, "target_prop", "val")

    # KILLS: `is_prediction=True` mutated to False
    poller.async_update_properties_from_state.assert_called_once_with(
        {"state": "ok", "not_the_prop": "val"}, is_prediction=True
    )

    # KILLS: `if k not in corrections and k != property_name:` mutated to `or` / `in`
    assert poller.register_pending_update.call_args_list == [
        call("target_prop", "val"),
        call("other_prop", "v2"),
    ]


def test_mutant_values_match_hasattr_dict_flip():
    """KILLS: not isinstance(val, dict) flip in _values_match."""
    # We pass a dict that HAS a "value" key.
    # The code: `if hasattr(val, "value") and not isinstance(val, dict): val = val.value`
    # It must NOT extract the value from the dict. It must compare the dicts.
    d1 = {"value": 1}
    d2 = {"value": 2}
    # If the mutant removes `not isinstance(..., dict)`, it will extract 1 and 2 and compare them.
    # We want to ensure it compares the dicts themselves.
    assert YamlStatePoller._values_match(d1, d1) is True
    assert YamlStatePoller._values_match(d1, d2) is False


def test_mutant_inject_value_connection_template_json_key():
    """KILLS: parsed.get("json", parsed) mutated to parsed.get(None, parsed)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}

    prop = MagicMock(id="good_sleep")
    del prop.convert_hass_to_dev
    prop.connection_template = Template(
        '{"json": {"options": ["Sleep_{{ value | int }}"]}}',
        hass=MagicMock(data={}),
    )
    poller._get_state_node_from_prop = MagicMock(return_value="Device.GoodSleep")

    poller._inject_value_into_state(prop, target_state, 5)

    # When unmutated: payload = {"options": ["Sleep_5"]}, dev_val becomes "Sleep_5"
    # When mutated with .get(None, parsed): payload remains {"json": {"options": ["Sleep_5"]}},
    # "options" not in payload, so dev_val remains 5 != "Sleep_5".
    assert target_state.get("Device", {}).get("GoodSleep") == "Sleep_5"


@pytest.mark.asyncio
async def test_mutant_predict_and_correct_enum_unwrapping():
    """KILLS: new_value is None and isinstance(new_value, dict) flips."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    fake_memory_state = {"mode_node": "cool"}
    poller.controller.loader.state_getter = NakedObj(value=fake_memory_state)

    class MockModeEnum:
        """Mock enum for test."""

        value = "heat"

    fake_prop = MagicMock(id="mode")
    fake_prop.value = "cool"
    del fake_prop.convert_hass_to_dev
    poller.controller.loader.operations = {"mode": fake_prop}
    poller._get_state_node_from_prop = MagicMock(return_value="mode_node")
    poller.async_update_properties_from_state = AsyncMock(return_value={})

    enum_val = MockModeEnum()
    await poller.async_predict_and_correct_state(None, "mode", enum_val)

    # KILLS:
    # 1. new_value is not None -> new_value is None
    # 2. not isinstance(new_value, dict) -> isinstance(new_value, dict)
    assert fake_prop.value == "heat", (
        "Mutant survived: Enum was not unwrapped to .value!"
    )
    assert fake_memory_state["mode_node"] == "heat"
    assert not hasattr(fake_prop.value, "value"), (
        "Property value should be primitive unwrapped string!"
    )


def test_mutant_inject_value_rendered_not_string():
    """KILLS: if rendered and isinstance(rendered, str): mutated to `or` (M24)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}
    prop = MagicMock(id="test")
    del prop.convert_hass_to_dev
    prop.connection_template = Template("doesnt_matter", hass=MagicMock())
    poller._get_state_node_from_prop = MagicMock(return_value="Node")

    # If render_template returns bytes, isinstance(rendered, str) is False.
    # Unmutated: False. Mutated (or): True, proceeds to json_loads(bytes) which succeeds!
    # Result: mutated code modifies target_state, unmutated does not.
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.render_template",
        return_value=b'{"json": {"options": ["Mutated!"]}}',
    ):
        poller._inject_value_into_state(prop, target_state, 5)

    # Unmutated should use the default dev_val (5).
    # Mutated will parse the bytes and use "Mutated!".
    assert target_state.get("Node") == 5, "Mutant survived: parsed bytes payload!"


def test_mutant_inject_value_no_json_key():
    """KILLS: parsed.get("json", parsed) mutated to .get("json", None) (M29)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}
    prop = MagicMock(id="test")
    del prop.convert_hass_to_dev
    # The JSON string directly has "options", no "json" key.
    prop.connection_template = Template(
        '{"options": ["DirectVal"]}', hass=MagicMock(data={})
    )
    poller._get_state_node_from_prop = MagicMock(return_value="Node")

    poller._inject_value_into_state(prop, target_state, 5)

    # Unmutated: payload becomes {"options": ["DirectVal"]}, extracts "DirectVal".
    # Mutated: payload becomes None, fails isinstance(payload, dict), dev_val unchanged (5).
    assert target_state.get("Node") == "DirectVal", (
        "Mutant survived: parsed.get fell back to None!"
    )


def test_mutant_inject_value_options_not_list():
    """KILLS: isinstance(payload['options'], list) mutated to `or` (M34)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}
    prop = MagicMock(id="test")
    del prop.convert_hass_to_dev
    # "options" is a string, not a list!
    prop.connection_template = Template(
        '{"options": "StringVal"}', hass=MagicMock(data={})
    )
    poller._get_state_node_from_prop = MagicMock(return_value="Node")

    poller._inject_value_into_state(prop, target_state, 5)

    # Unmutated: isinstance(list) is False, block skipped.
    # Mutated: `or` makes it True, enters block, payload["options"][0] extracts "S"!
    assert target_state.get("Node") != "S", (
        "Mutant survived: options list check was bypassed!"
    )


def test_mutant_apply_anti_flicker_global_evict():
    """KILLS: global_evict = True mutated to False in _apply_anti_flicker_locks (Line 790)."""
    poller = YamlStatePoller(MagicMock())
    now = time.monotonic()

    # op_evict has should_evict_all_locks returning True
    op_evict = MagicMock(id="power")
    op_evict.should_evict_all_locks.return_value = True

    # op_target has a pending lock
    op_target = MagicMock(id="temperature")
    op_target.calculate_value_from_state.return_value = 24
    del op_target.should_evict_all_locks

    def get_state_node(op):
        if op.id == "power":
            return "power_node"
        return "temp_node"

    poller._get_state_node_from_prop = get_state_node

    all_props = [op_evict, op_target]
    device_to_process = {"temp_node": 24}
    pure_device_to_process = {"temp_node": 24}

    # Set pending update with age past LOCK_SHIELD_SEC (e.g. 5s)
    poller._pending_updates = {
        "temperature": (24, now - (poller.LOCK_SHIELD_SEC + 1.0))
    }

    # changed_keys does NOT include "temp_node", but global_evict is True
    changed_keys = {"power_node"}

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=changed_keys,
    )

    op_evict.should_evict_all_locks.assert_called_with(
        pure_device_to_process, changed_keys
    )

    # When unmutated: global_evict is True -> can_release is True -> lock is released
    # When mutated (global_evict = False): can_release is False -> lock remains in _pending_updates
    assert "temperature" not in poller._pending_updates


def test_mutant_apply_anti_flicker_hass_attr_mapping():
    """KILLS: if hass_attr != op_id mutated to == in _apply_anti_flicker_locks (Line 809)."""
    poller = YamlStatePoller(MagicMock())
    now = time.monotonic()

    # Create an operation where hass_attr differs from op.id
    op = MagicMock(id="target_temperature_op")
    del op.should_evict_all_locks
    del op.convert_hass_to_dev
    op.calculate_value_from_state.return_value = 22
    poller._get_state_node_from_prop = MagicMock(return_value="target_temp_node")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="target_temperature")

    all_props = [op]
    device_to_process = {"target_temp_node": 20}
    pure_device_to_process = {"target_temp_node": 20}

    # The pending update is registered under the HA attribute name ("target_temperature")
    poller._pending_updates = {"target_temperature": (22, now - 1.0)}

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=None,
    )

    # Unmutated: props_by_id["target_temperature"] = op -> op found -> lock enforced on op
    # Mutated (if hass_attr == op_id): props_by_id["target_temperature"] not set -> not enforced
    assert device_to_process["target_temp_node"] == 22


def test_mutant_apply_anti_flicker_changed_keys_is_not_none_or():
    """KILLS: changed_keys is not None mutated to is None in _apply_anti_flicker_locks."""
    poller = YamlStatePoller(MagicMock())
    now = time.monotonic()

    op = MagicMock(id="mode")
    del op.should_evict_all_locks
    # Physical state is "cool", but pending is "heat" -> values do NOT match
    op.calculate_value_from_state.return_value = "cool"
    poller._get_state_node_from_prop = MagicMock(return_value="mode_node")

    all_props = [op]
    device_to_process = {"mode_node": "cool"}
    pure_device_to_process = {"mode_node": "cool"}

    # Lock age is past LOCK_SHIELD_SEC (e.g. 5s) but below LOCK_PHYSICAL_TIMEOUT_SEC (15s)
    lock_age = poller.LOCK_SHIELD_SEC + 3.0
    poller._pending_updates = {"mode": ("heat", now - lock_age)}

    # Push update arrived with changed_keys containing mode_node
    changed_keys = {"mode_node"}

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=changed_keys,
    )

    # When unmutated: changed_keys is not None (True) -> lock is released
    # When mutated (changed_keys is None): condition is False -> lock remains in _pending_updates
    assert "mode" not in poller._pending_updates


def test_mutant_apply_anti_flicker_expired_ttl_continue():
    """KILLS: continue mutated to break in _apply_anti_flicker_locks (Line 820)."""
    poller = YamlStatePoller(MagicMock())
    now = time.monotonic()

    # Create two properties: one expired, one active
    op_expired = MagicMock(id="expired_prop")
    del op_expired.should_evict_all_locks
    del op_expired.calculate_value_from_state
    del op_expired.convert_hass_to_dev

    op_active = MagicMock(id="active_prop")
    del op_active.should_evict_all_locks
    del op_active.calculate_value_from_state
    del op_active.convert_hass_to_dev

    poller._get_state_node_from_prop = lambda op: "node_" + op.id
    poller._get_hass_attr_for_op_id = lambda op_id: op_id

    all_props = [op_expired, op_active]
    device_to_process = {"node_expired_prop": "old1", "node_active_prop": "old2"}
    pure_device_to_process = {"node_expired_prop": "old1", "node_active_prop": "old2"}

    # Set pending updates: first one expired (> LOCK_TTL_SEC), second one fresh (5s)
    poller._pending_updates = {
        "expired_prop": ("val1", now - (poller.LOCK_TTL_SEC + 10.0)),
        "active_prop": ("val2", now - 5.0),
    }

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=None,
    )

    # 1. The expired lock must be deleted
    assert "expired_prop" not in poller._pending_updates

    # 2. The active lock MUST be processed and injected into device_to_process
    # If continue was mutated to break, active_prop would never be processed!
    assert "active_prop" in poller._pending_updates
    assert poller._pending_updates["active_prop"][0] == "val2"
    assert device_to_process["node_active_prop"] == "val2"


def test_mutant_predict_dependency_cascades_continue():
    """KILLS: continue mutated to break in _predict_dependency_cascades (Line 913)."""
    poller = YamlStatePoller(MagicMock())

    # op1 is invalid (is_valid returns False)
    op1 = MagicMock(id="op1_invalid")
    op1.is_valid.return_value = False
    del op1.get_valid_values

    # op2 is valid and needs cascade correction
    op2 = MagicMock(id="op2_valid")
    op2.is_valid.return_value = True
    del op2.get_valid_values
    op2.values = ["val_a", "val_b"]
    poller._get_prop_value = MagicMock(
        side_effect=lambda op: "invalid_val" if op.id == "op2_valid" else None
    )
    poller._get_state_node_from_prop = MagicMock(return_value="op2_node")

    poller.controller.loader.operations = {
        "op1": op1,
        "op2": op2,
    }

    corrections = poller._predict_dependency_cascades({})

    # Unmutated (continue): op1 skipped, op2 processed -> op2 corrected to "val_a"
    # Mutated (break): loop breaks at op1, op2 never processed -> corrections is empty
    assert corrections == {"op2_valid": "val_a"}


@pytest.mark.asyncio
async def test_mutant_async_merge_device_state_is_none():
    """KILLS: if getattr(..., '_pure_network_state', None) is None flip (Line 1071)."""
    poller = YamlStatePoller(MagicMock())
    poller.async_update_properties_from_state = AsyncMock()

    # Pre-existing state in _pure_network_state, while st_getter.value is None
    poller._pure_network_state = {"existing_key": "existing_value"}
    poller.controller.loader.state_getter = NakedObj(value=None)

    res = await poller.async_merge_device_state({"new_key": "new_value"})

    # Unmutated: _pure_network_state is not None, so line 1071 is skipped.
    # not self._pure_network_state is False.
    # update() is called with new_data -> returns True.
    # Mutated (is not None): line 1071 executes -> self._pure_network_state = {}
    # not self._pure_network_state is True -> st_getter.value is None -> returns False!
    assert res is True
    assert poller._pure_network_state == {
        "existing_key": "existing_value",
        "new_key": "new_value",
    }


@pytest.mark.asyncio
async def test_mutant_async_update_properties_st_getter_and_value():
    """KILLS: if st_getter and st_getter.value mutated to or (Line 962)."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # st_getter exists (truthy object), but value is None
    poller.controller.loader.state_getter = NakedObj(value=None)

    poller._extract_device_nodes = MagicMock()

    # Call with full_device_state=None
    res = await poller.async_update_properties_from_state(full_device_state=None)

    # Unmutated: `st_getter and st_getter.value` is False -> returns {} without calling extract
    # Mutated (or): `st_getter or st_getter.value` is True -> calls _extract_device_nodes
    assert res == {}
    poller._extract_device_nodes.assert_not_called()


def test_untested_device_state_and_pure_network_state_properties():
    """Test full branch coverage for device_state and pure_network_state properties."""
    poller = YamlStatePoller(MagicMock())

    # --- Test device_state ---
    poller._last_device_state = None
    assert poller.device_state == {}

    poller._last_device_state = {"power": "on"}
    assert poller.device_state == {"power": "on"}

    # --- Test pure_network_state ---
    # 1. None state
    poller._pure_network_state = None
    assert poller.pure_network_state == {}

    # 2. Empty dict
    poller._pure_network_state = {}
    assert poller.pure_network_state == {}

    # 3. Non-dict type
    poller._pure_network_state = ["not", "a", "dict"]  # type: ignore[assignment]
    assert poller.pure_network_state == {}

    # 4. Standard dict without Devices key
    poller._pure_network_state = {"temp": 21, "mode": "cool"}
    assert poller.pure_network_state == {"temp": 21, "mode": "cool"}

    # 5. Devices key is a valid list of dicts (Samsung format unwrap)
    poller._pure_network_state = {
        "Devices": [{"id": "0", "power": "on"}, {"id": "1", "power": "off"}]
    }
    assert poller.pure_network_state == {"id": "0", "power": "on"}

    # 6. Devices key is empty list
    poller._pure_network_state = {"Devices": []}
    assert poller.pure_network_state == {"Devices": []}

    # 7. Devices key is not a list (e.g. dict or str)
    poller._pure_network_state = {"Devices": "invalid"}
    assert poller.pure_network_state == {"Devices": "invalid"}

    # 8. Devices list contains non-dict first element
    poller._pure_network_state = {"Devices": ["invalid_string"]}
    assert poller.pure_network_state == {"Devices": ["invalid_string"]}
