# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,not-callable,invalid-sequence-index,unsubscriptable-object
import copy
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    CONFIG_DEVICE,
    DEVICE_TYPE_SAMSUNG_2878,
)
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller


class NakedObj:
    """Objeto estricto que falla rápido (Fail-Fast). Si el atributo no existe, detona AttributeError."""

    def __init__(self, **kwargs):
        self.hass = None
        self.debug = False
        self.name = "TestName"
        self.ip_address = "192.168.1.100"
        self.available = True
        self.device_id = "XXXX"
        self.log_prefix = "TestLog"
        if "_value" not in kwargs:
            self.value = None
        self.sensors = {}
        self.properties = {}
        self.operations = {}
        self._attributes = {}
        for k, v in kwargs.items():
            setattr(self, k, v)

    def update_state_attributes(self, new_attrs):
        self._attributes = new_attrs


class DummyController:
    """Controlador simulado y blindado para los Sniper Tests."""

    def __init__(self, **kwargs):
        self.log_prefix = "TestLog"
        self.ip_address = "192.168.1.100"
        self.name = "TestName"
        self.debug = False
        self.available = True
        self.config = {}
        self.device_id = ""
        # Base loader structure to prevent unintended crashes
        self.loader = NakedObj(
            operations={},
            properties={},
            sensors={},
            is_fully_initialized=True,
            _parsed_yaml_cache={},
            state_getter=None,
        )
        self._attributes = {}
        for k, v in kwargs.items():
            setattr(self, k, v)

    def update_state_attributes(self, new_attrs):
        self._attributes = new_attrs


async def _helper_build_device_state_from_props(self):
    loader = getattr(self.controller, "loader", None)
    if not loader:
        raise AttributeError("Loader is missing")
    if not hasattr(loader, "state_getter") or loader.state_getter is None:
        raise AttributeError("state_getter is missing")
    st_val = self._get_prop_value(loader.state_getter)
    if st_val is None:
        raise AttributeError("state_getter value is None")
    state = copy.deepcopy(st_val) if isinstance(st_val, dict) else {}
    for prop in self._all_props():
        prop_id = getattr(prop, "id", None)
        val = self._get_prop_value(prop)
        if val is not None and prop_id:
            self._inject_value_into_state(prop, state, val)
    return state


async def _helper_build_device_state_from_hass(self, current_hass_state=None):
    if current_hass_state is None:
        return None
    st_getter = getattr(self.controller.loader, "state_getter", None)
    val = self._get_prop_value(st_getter) if st_getter else None
    return copy.deepcopy(val) if isinstance(val, dict) else {}


def _helper_calculate_structured_state(self, full_device_state=None):
    if full_device_state is None:
        st_getter = getattr(self.controller.loader, "state_getter", None)
        full_device_state = self._get_prop_value(st_getter) if st_getter else None
    if not full_device_state or not isinstance(full_device_state, dict):
        return None
    loader = getattr(self.controller, "loader", None)
    ops = getattr(loader, "operations", {}) if loader else {}
    props = getattr(loader, "properties", {}) if loader else {}
    sensors = getattr(loader, "sensors", {}) if loader else {}
    st_getter = getattr(loader, "state_getter", None)
    all_p = (
        ([st_getter] if st_getter else [])
        + list(ops.values())
        + list(props.values())
        + list(sensors.values())
    )
    for prop in all_p:
        prop_id = getattr(prop, "id", None)
        if prop_id and hasattr(prop, "calculate_value_from_state"):
            prop.calculate_value_from_state(full_device_state)
    return copy.deepcopy(full_device_state)


@pytest.fixture(autouse=True)
def setup_poller_helpers(monkeypatch):
    monkeypatch.setattr(
        YamlStatePoller,
        "_build_device_state_from_props",
        _helper_build_device_state_from_props,
        raising=False,
    )
    monkeypatch.setattr(
        YamlStatePoller,
        "_build_device_state_from_hass",
        _helper_build_device_state_from_hass,
        raising=False,
    )
    monkeypatch.setattr(
        YamlStatePoller,
        "_calculate_structured_state",
        _helper_calculate_structured_state,
        raising=False,
    )


@pytest.mark.asyncio
async def test_sniper_predict_and_correct_missing_ids_and_shutdown():
    mock_controller = NakedObj(log_prefix="TEST")
    poller = YamlStatePoller(mock_controller)

    op = NakedObj(id="op1")
    prop = NakedObj(id="prop1")
    poller.controller.loader = NakedObj(
        is_fully_initialized=True,
        state_getter=NakedObj(value={"some": "state"}),
        operations={"op1": op},
        properties={"prop1": prop},
        connection=NakedObj(stop_listening=AsyncMock(), close=AsyncMock()),
    )
    poller._build_device_state_from_props = AsyncMock(return_value={"future": "state"})
    poller.async_update_properties_from_state = AsyncMock(return_value={"a": 1})

    _, corrections = await poller.async_predict_and_correct_state(
        NakedObj(), "op1", "val"
    )
    assert corrections == {}

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        await poller.async_shutdown()
        mock_sleep.assert_called_once_with(1.0)
    assert poller.controller.loader.connection is None


@pytest.mark.asyncio
async def test_sniper_update_properties_cache_and_get_fallbacks():
    mock_controller = NakedObj(log_prefix="TEST", device_id="0")
    poller = YamlStatePoller(mock_controller)

    class StrictCache(dict):
        def get(self, key, default=None):
            if key is None:
                raise KeyError("Mutant detected")
            return super().get(key, default)

    poller.controller.loader = NakedObj(
        is_fully_initialized=True,
        _parsed_yaml_cache=StrictCache({"0": {}}),
        operations={},
        properties={},
        sensors={},
    )
    poller._rebuild_attributes = MagicMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.exception"
    ) as mock_exc:
        await poller.async_update_properties_from_state({"dummy": "data"})
        mock_exc.assert_not_called()

    # Inject dummy key to evade empty ifs but force getter fallback
    poller.controller.loader._parsed_yaml_cache["0"][CONFIG_DEVICE] = {
        "identifiers": {"dummy": "val"}
    }

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.get_value_by_path",
        side_effect=[[{"id": "0"}], "0"],
    ) as mock_get_path:
        await poller.async_update_properties_from_state({"dummy": "data"})
        calls = mock_get_path.call_args_list
        assert len(calls) >= 2


@pytest.mark.asyncio
async def test_sniper_update_properties_pending_and_is_valid_mutations():
    """Kills mutants L534 y L567 validando los parámetros de delegación estrictos."""
    mock_controller = NakedObj(log_prefix="TEST", debug=False)
    poller = YamlStatePoller(mock_controller)

    # Intercept L534 (None substitution in pending update)
    prop = NakedObj(id="prop1")
    prop.convert_hass_to_dev = MagicMock(return_value="dev_pending_val")
    prop.set_device_state_for_values = MagicMock()

    # Intercept L567 (None substitution in is_valid)
    op = NakedObj(id="op1", value="a", values=["a", "b"])
    op.is_valid = MagicMock(return_value=True)

    poller.controller.loader = NakedObj(
        is_fully_initialized=True,
        operations={"op1": op},
        properties={"prop1": prop},
        sensors={},
    )
    poller._rebuild_attributes = MagicMock()

    # Insert pending update < 15 seconds to force L534
    poller._pending_updates = {"prop1": ("pending_val", time.monotonic() - 5.0)}

    with patch.object(
        poller,
        "_get_state_node_from_prop",
        side_effect=lambda p: getattr(p, "id", "key") + "_key",
    ) as mock_get_key:
        base_state = {"dummy": "state"}
        await poller.async_update_properties_from_state(base_state)

        # 1. Verification of L534
        mock_get_key.assert_any_call(prop)
        assert base_state.get("prop1_key") == "dev_pending_val", (
            "Mutant L534: Injection failed due to passing None to key finder"
        )

        # 2. Verification of L567
        op.is_valid.assert_called_once()
        args, _ = op.is_valid.call_args
        # Ensure is_valid received the real dictionary and not a None introduced by mutmut
        assert args[0] is not None
        assert args[0] == base_state, (
            "Mutant L567: is_valid evaluated blindly with None"
        )


async def test_async_merge_device_state_logic_flips():
    """Kills mutants de 'and -> or' y 'return False -> return True'."""
    # Object without 'get_current_state_callback'. If 'and' changes to 'or' (M5),
    # will attempt executing non-existent property and raise AttributeError.
    mock_controller = NakedObj(loader=NakedObj(state_getter=None), log_prefix="Test")
    poller = YamlStatePoller(mock_controller)

    # If M14/15 changes "if not st_getter: return False" to "return True", this assertion fails.
    res = await poller.async_merge_device_state({"new": "data"})
    assert res is False


async def test_update_properties_private_value_pending():
    """Kills mutants que deshabilitan la asignación de hasattr('_value')."""
    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)

    # Property intentionally WITHOUT 'value', only with '_value'
    prop_private = NakedObj(
        id="hidden_prop", _value="old_val", async_update_state=lambda *args: None
    )
    if hasattr(prop_private, "value"):
        delattr(prop_private, "value")

    poller.controller.loader.operations = {"hidden_prop": prop_private}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    poller.controller.loader.is_fully_initialized = True

    poller.register_pending_update("hidden_prop", "NEW_DATA")

    await poller.async_update_properties_from_state({"raw": "data"})

    # If mutmut altered hasattr('_value') statements or assignment, '_value' remains "old_val"
    assert prop_private._value == "NEW_DATA"


@pytest.mark.asyncio
async def test_sniper_prediction_forensic_logging_guards_m6_m81_m82():
    """Kills mutant M6 (L935 and->or), M81 (L1018 and->or), and M82 (L1018 or->and).

    Validates strict logical boundary for forensic prediction logging:
    - L935: 'if is_prediction and self._pending_updates:'
    - L1018: 'if is_prediction and (self._pending_updates or corrections):'
    """
    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.operations = {}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.debug"
    ) as mock_debug:
        # 1. is_prediction=False, pending_updates is non-empty -> NEITHER start NOR end log
        # KILLS M6: 'is_prediction or self._pending_updates' would log start when False
        # KILLS M81: 'is_prediction or (...)' would log end when False
        poller._pending_updates = {"temp": ("24", time.monotonic())}
        await poller.async_update_properties_from_state(
            {"Devices": [{}]}, is_prediction=False, force_update=True
        )
        assert not any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), "Mutant M6 survived: Prediction started logged when is_prediction=False"
        assert not any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), "Mutant M81 survived: Prediction ended logged when is_prediction=False"

        # 2. is_prediction=True, pending_updates is EMPTY, corrections is EMPTY -> NEITHER log
        # KILLS M6: 'is_prediction or self._pending_updates' would log start when True and pending={}
        # KILLS M81: 'is_prediction or (...)' would log end when True and both are empty
        mock_debug.reset_mock()
        poller._pending_updates = {}
        await poller.async_update_properties_from_state(
            {"Devices": [{}]}, is_prediction=True
        )
        assert not any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), "Mutant M6 survived: Prediction started logged when pending_updates is empty"
        assert not any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), (
            "Mutant M81 survived: Prediction ended logged when pending and corrections are empty"
        )

        # 3. is_prediction=True, pending_updates NON-EMPTY, corrections EMPTY -> BOTH start and end logs
        # KILLS M82: 'is_prediction and (self._pending_updates and corrections)' would evaluate False
        # and NOT log Prediction ended when corrections is empty!
        mock_debug.reset_mock()
        poller._pending_updates = {"temp": ("24", time.monotonic())}
        await poller.async_update_properties_from_state(
            {"Devices": [{}]}, is_prediction=True
        )
        assert any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), "Normal behavior failed: Prediction started not logged"
        assert any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), (
            "Mutant M82 survived: Prediction ended NOT logged when corrections is empty but pending exists"
        )

        # 4. is_prediction=True, pending_updates EMPTY, corrections NON-EMPTY -> ONLY end log
        # KILLS M82: 'is_prediction and (self._pending_updates and corrections)' would evaluate False
        # and NOT log Prediction ended when pending_updates is empty!
        mock_debug.reset_mock()
        poller._pending_updates = {}
        poller._predict_dependency_cascades = MagicMock(
            return_value={"fan_mode": "auto"}
        )
        await poller.async_update_properties_from_state(
            {"Devices": [{}]}, is_prediction=True
        )
        assert not any(
            "[Forensic] Prediction started" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), "Mutant M6 survived: Prediction started logged when pending_updates is empty"
        assert any(
            "[Forensic] Prediction ended" in str(c.args[0])
            for c in mock_debug.call_args_list
        ), (
            "Mutant M82 survived: Prediction ended NOT logged when pending is empty but corrections exists"
        )


async def test_async_update_properties_backup_native_injection():
    """Kill mutant on L1010 of controller_yaml_polling.py: 'if val is not None:' mutated to 'if val is None:'."""
    ctrl = DummyController()
    poller = YamlStatePoller(ctrl)
    poller._predict_dependency_cascades = MagicMock(return_value={})
    poller._inject_value_into_state = MagicMock()
    dummy_prop = NakedObj(id="target_temperature", value=20)
    ctrl.loader.properties = {"target_temperature": dummy_prop}
    poller._pending_updates = {"target_temperature": (24, time.monotonic())}

    await poller.async_update_properties_from_state(
        {"Devices": [{}]}, is_prediction=False, force_update=True
    )

    # Mutant changed 'if val is not None' to 'if val is None', which bypasses backup native injection
    assert poller._inject_value_into_state.call_count == 2
    assert poller._inject_value_into_state.call_args_list[1][0][0] == dummy_prop
    assert poller._inject_value_into_state.call_args_list[1][0][2] == 24


@pytest.mark.asyncio
async def test_sniper_icmp_check_diagnostic_fallback_and_existing():
    """Kill mutant M13 on L344: 'or' mutated to 'and' in self._last_icmp_diagnostic fallback."""
    ctrl = DummyController(
        ip_address="192.168.1.50", config={CONF_DEVICE_TYPE: "generic_hvac"}
    )
    poller = YamlStatePoller(ctrl)

    # Scenario 1: get_last_network_diagnostic returns None -> fallback dict must be assigned
    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
            AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_polling.get_last_network_diagnostic",
            return_value=None,
        ),
    ):
        await poller._async_perform_icmp_check()
        assert poller.last_icmp_diagnostic is not None, (
            "Mutant M13 survived: _last_icmp_diagnostic is None when get_last_network_diagnostic returns None"
        )
        assert poller.last_icmp_diagnostic["is_reachable"] is True
        assert poller.last_icmp_diagnostic["status"] == "alive"
        assert "timestamp" in poller.last_icmp_diagnostic

    # Scenario 2: get_last_network_diagnostic returns existing dict -> existing dict must be preserved
    existing_diag = {"is_reachable": True, "status": "alive", "rtt_ms": 1.23}
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
        assert poller.last_icmp_diagnostic == existing_diag, (
            "Mutant M13 survived: existing diagnostic was replaced by fallback under 'and'"
        )


@pytest.mark.asyncio
async def test_sniper_async_update_state_pure_network_state_deepcopy():
    """Kill mutant M40 (self._pure_network_state = None), M42 (copy.deepcopy -> copy.copy), and M97 (cast(None))."""
    ctrl = DummyController(
        ip_address=None, config={CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    )
    poller = YamlStatePoller(ctrl)

    initial_nested = {"mode": "cool", "sub": {"temp": 21}}
    raw_payload = {"Devices": [initial_nested]}

    ctrl.loader.state_getter = NakedObj(
        value={"ok": True},
        async_update_state=AsyncMock(return_value=raw_payload),
    )
    poller.async_update_properties_from_state = AsyncMock()

    # Kills M97: verifies cast receives dict[str, Any] | None and not None
    def spy_cast(typ, val):
        assert typ is not None, (
            "Mutant M97 survived: cast(None, ...) was called instead of cast(dict[str, Any] | None, ...)"
        )
        return val

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.cast",
        side_effect=spy_cast,
    ):
        res = await poller.async_update_state()
    assert res == {"ok": True}

    # Verify M40: _pure_network_state must not be None
    assert poller._pure_network_state is not None, (
        "Mutant M40 survived: _pure_network_state was set to None"
    )
    assert poller._pure_network_state == {
        "Devices": [{"mode": "cool", "sub": {"temp": 21}}]
    }

    # Verify M42: deepcopy ensures mutating raw_payload does NOT mutate _pure_network_state
    assert poller._pure_network_state is not raw_payload
    assert poller._pure_network_state["Devices"] is not raw_payload["Devices"]
    assert poller._pure_network_state["Devices"][0] is not raw_payload["Devices"][0]
    assert (
        poller._pure_network_state["Devices"][0]["sub"]
        is not raw_payload["Devices"][0]["sub"]
    )

    # Mutate the source dictionary post-update
    raw_payload["Devices"][0]["sub"]["temp"] = 99
    assert poller._pure_network_state["Devices"][0]["sub"]["temp"] == 21, (
        "Mutant M42 survived: shallow copy allowed mutation of raw payload to leak into _pure_network_state"
    )
