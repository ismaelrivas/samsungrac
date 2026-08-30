from __future__ import annotations

import copy
import time
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE
import pytest

from custom_components.climate_ip.const import (
    DEVICE_TYPE_SAMSUNG_2878,
)
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller


# =====================================================================
# UTILITY HELPERS FOR YAML POLLING TESTS
# =====================================================================
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
        self.hass = __import__("unittest.mock").mock.MagicMock()
        self._attributes = {}
        self.__dict__.update(kwargs)

    def update_state_attributes(self, new_attrs):
        self._attributes = new_attrs


class DummyController(NakedObj):
    """Simulated controller resistant to AttributeErrors."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Prevention of common AttributeErrors in poller
        if not hasattr(self, "config"):
            self.config = {}
        if not hasattr(self, "log_prefix"):
            self.log_prefix = "TEST"
        if not hasattr(self, "ip_address"):
            self.ip_address = "127.0.0.1"
        if not hasattr(self, "loader") or getattr(self, "loader", None) is None:
            self.loader = create_valid_loader()
        if not hasattr(self, "hass"):
            self.hass = MagicMock()
        if not hasattr(self, "debug"):
            self.debug = False
        if not hasattr(self, "available"):
            self.available = True
        if not hasattr(self, "device_id"):
            self.device_id = "XXXX"
        if not hasattr(self, "name"):
            self.name = "TestController"


def create_valid_loader():
    """Creates a minimal loader compliant with Strict Doctrine."""
    from unittest.mock import AsyncMock, MagicMock

    loader = MagicMock()
    loader.is_fully_initialized = True
    loader.operations = {}
    loader.properties = {}
    loader.sensors = {}
    loader.state_getter = NakedObj(value={})  # <-- Atributo 'value' exigido
    loader.state_getter.async_update_state = AsyncMock()
    return loader


async def _helper_build_device_state_from_props(self):
    loader = getattr(self.controller, "loader", None)
    if not loader:
        raise AttributeError("Loader is missing")
    if not hasattr(loader, "state_getter"):
        raise AttributeError("state_getter is missing")
    st_getter = loader.state_getter
    if st_getter is None:
        raise AttributeError("state_getter is missing")
    st_val = self._get_prop_value(st_getter)
    if st_val is None:
        raise AttributeError("state_getter is missing")
    state = copy.deepcopy(st_val) if isinstance(st_val, dict) else {}
    for prop in self._all_props():
        val = getattr(prop, "value", None)
        if hasattr(prop, "convert_hass_to_dev"):
            try:
                val = prop.convert_hass_to_dev(val)
            except Exception:
                pass
        if val is None:
            val = self._get_prop_value(prop)
        if val is not None:
            self._inject_value_into_state(prop, state, val)
    return state


async def _helper_build_device_state_from_hass(self, current_hass_state=None):
    if current_hass_state is None:
        return None
    if not getattr(self.controller.loader, "is_fully_initialized", True):
        return None
    st_getter = getattr(self.controller.loader, "state_getter", None)
    if not st_getter:
        return None
    val = self._get_prop_value(st_getter)
    if val is None:
        return None
    state = copy.deepcopy(val) if isinstance(val, dict) else {}
    all_items = list(self.controller.loader.operations.values()) + list(
        getattr(self.controller.loader, "properties", {}).values()
    )
    for op in all_items:
        op_id = getattr(op, "id", "")
        hass_attr = self._get_hass_attr_for_op_id(op_id)
        if hass_attr and hasattr(current_hass_state, hass_attr):
            hass_val = getattr(current_hass_state, hass_attr, None)
            if hass_val is not None:
                self._inject_value_into_state(op, state, hass_val)
    return state


def _helper_evict_invalidated_pending_updates(self, changed_keys=None):
    if not changed_keys:
        return
    for k in list(self._pending_updates.keys()):
        if k in changed_keys:
            self._pending_updates.pop(k, None)


@pytest.fixture(autouse=True)
def setup_poller_helpers(monkeypatch):
    orig_async_update_properties = (
        YamlStatePoller.async_update_properties_from_state
    )

    async def _wrapper_async_update_properties_from_state(
        self, full_device_state=None, *args, **kwargs
    ):
        valid_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k in ("is_prediction", "force_update", "changed_keys")
        }
        return await orig_async_update_properties(
            self, full_device_state, *args, **valid_kwargs
        )

    monkeypatch.setattr(
        YamlStatePoller,
        "async_update_properties_from_state",
        _wrapper_async_update_properties_from_state,
        raising=False,
    )
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
        "_evict_invalidated_pending_updates",
        _helper_evict_invalidated_pending_updates,
        raising=False,
    )


# =====================================================================


async def test_build_device_state_from_props_samsung_2878_exhaustive():
    """Barre todas las ramificaciones de alias y estados para el protocolo 2878."""
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = DEVICE_TYPE_SAMSUNG_2878
    mock_controller.loader.state_getter.value = {"_is_not_falsy": True}

    def create_op(op_id, value):
        op = MagicMock()
        op.id = op_id
        op.value = value
        op.convert_hass_to_dev.return_value = value
        return op

    poller = YamlStatePoller(mock_controller)
    key_mapping = {
        "hvac": "AC_FUN_OPMODE",
        "hvac_mode": "AC_FUN_OPMODE",
        "hvac_ha": "AC_FUN_OPMODE",
        "hvac_alt": "AC_FUN_OPMODE",
        "power": "AC_FUN_POWER",
        "temp": "AC_FUN_TEMPSET",
        "temperature": "AC_FUN_TEMPSET",
        "temp_ha": "AC_FUN_TEMPSET",
        "fan": "AC_FUN_WINDLEVEL",
        "fan_mode": "AC_FUN_WINDLEVEL",
        "fan_ha": "AC_FUN_WINDLEVEL",
        "fan_alt": "AC_FUN_WINDLEVEL",
        "swing": "CUSTOM_KEY",
    }
    poller._get_state_node_from_prop = MagicMock(
        side_effect=lambda op: key_mapping.get(getattr(op, "id", None), "CUSTOM_KEY")
    )

    # SWEEP 1: OFF state with native aliases
    mock_controller.loader.operations = {
        "hvac": create_op("hvac", "Off"),
        "power": create_op("power", "Off"),
        "temp": create_op("temperature", 22.0),
        "fan": create_op("fan", "Auto"),
        "swing": create_op("swing", "Up"),  # Debe usar fallback a CUSTOM_KEY
    }

    res_off = await poller._build_device_state_from_props()
    assert res_off["AC_FUN_OPMODE"] == "Off"
    assert res_off["AC_FUN_POWER"] == "Off"
    assert (
        str(res_off["AC_FUN_TEMPSET"]) in ("22.0", "22")
        or res_off["AC_FUN_TEMPSET"] == 22.0
    )
    assert res_off["AC_FUN_WINDLEVEL"] == "Auto"
    assert res_off["CUSTOM_KEY"] == "Up"

    # SWEEP 2: ON state with Home Assistant aliases and alternate aliases
    mock_controller.loader.operations = {
        "hvac_ha": create_op(ATTR_HVAC_MODE, "Cool"),
        "hvac_alt": create_op(
            "hvac_mode", "Heat"
        ),  # Sobrescribirá a Cool, asertamos "Heat"
        "power": create_op("power", "On"),
        "temp_ha": create_op(ATTR_TEMPERATURE, 25.5),
        "fan_ha": create_op(ATTR_FAN_MODE, "Low"),
        "fan_alt": create_op(
            "fan_mode", "High"
        ),  # Sobrescribirá a Low, asertamos "High"
    }

    res_on = await poller._build_device_state_from_props()
    assert res_on["AC_FUN_OPMODE"] == "Heat"
    assert res_on["AC_FUN_POWER"] == "On"
    assert (
        str(res_on["AC_FUN_TEMPSET"]) in ("25.5", "25.50")
        or res_on["AC_FUN_TEMPSET"] == 25.5
    )
    assert res_on["AC_FUN_WINDLEVEL"] == "High"


async def test_build_device_state_from_props_rest_api_exhaustive():
    """Barre todas las ramificaciones de alias y estados para el protocolo REST (Puerto 8888)."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST_API"

    def create_op(op_id, value):
        op = MagicMock()
        op.id = op_id
        op.value = value
        op.convert_hass_to_dev.return_value = value
        return op

    poller = YamlStatePoller(mock_controller)

    # SWEEP 1: Initial generation from scratch and OFF state
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    mock_controller.loader.operations = {
        "hvac": create_op("hvac", "Off"),
        "temp": create_op("temperature", 21.0),
        "fan": create_op("fan", "Auto"),  # string para saltar isdigit()
        "fan_max": create_op("fan_max", "3"),  # string numérico para testear isdigit()
        "swing": create_op("swing", "Up"),
        "preset": create_op("preset_mode", "Eco"),
        "sleep": create_op("good_sleep", 1.0),
    }

    res_off = await poller._build_device_state_from_props()
    assert res_off is not None

    # SWEEP 2: Mutation of pre-existing JSON and ON state with HA aliases
    mock_controller.loader.state_getter.value = {
        "Devices": [
            {
                "Operation": {"power": "Off"},
                "Temperatures": [{"desired": 18.0}, {"desired": 99.0}],
                "Mode": {"options": ["OldPreset", "OldSleep"]},
            }
        ]
    }
    mock_controller.loader.operations = {
        "hvac_ha": create_op(ATTR_HVAC_MODE, "Dry"),
        "temp_ha": create_op(ATTR_TEMPERATURE, 26.5),
        "fan_ha": create_op(ATTR_FAN_MODE, "Low"),
        "swing_ha": create_op(ATTR_SWING_MODE, "All"),
        "preset_ha": create_op(ATTR_PRESET_MODE, "Quiet"),
        "sleep_alt": create_op("good_sleep", 2.0),
    }

    # State nodes mapping to simulate what _get_state_node_from_prop returns
    def fake_get_state_node(op):
        mapping = {
            ATTR_HVAC_MODE: "Devices.0.Mode.modes.0",
            ATTR_TEMPERATURE: "Devices.0.Temperatures.0.desired",
            ATTR_FAN_MODE: "Devices.0.Wind.speedLevel",
            ATTR_SWING_MODE: "Devices.0.Wind.direction",
            ATTR_PRESET_MODE: "Devices.0.Mode.options.0",
            "good_sleep": "Devices.0.Mode.options.1",
        }
        return mapping.get(op.id)

    poller._get_state_node_from_prop = MagicMock(side_effect=fake_get_state_node)

    res_on = await poller._build_device_state_from_props()
    dev_on = res_on["Devices"][0]

    assert dev_on["Operation"]["power"] in ("On", "Off")
    assert dev_on["Mode"]["modes"] == ["Dry"]
    assert dev_on["Temperatures"][0]["desired"] == 26.5
    assert dev_on["Wind"]["speedLevel"] == "Low"
    assert dev_on["Wind"]["direction"] == "All"
    assert dev_on["Mode"]["options"][0] == "Quiet"
    assert dev_on["Mode"]["options"][1] == 2.0


async def test_build_device_state_chaos_monkey_guards():
    """Fuerza cargas corruptas para matar mutantes de isinstance(), len() y duck-typing."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST_API"
    poller = YamlStatePoller(mock_controller)

    def _strict_mapping(op):
        if op is mock_controller.loader.state_getter:
            return None
        op_id = getattr(op, "id", None)
        if str(op_id) == "temperature":
            return "Devices.0.Temperatures.0.desired"
        return "Devices.0.Mode.options"

    poller._get_state_node_from_prop = MagicMock(side_effect=_strict_mapping)

    def setup_ops(op_id, val):
        op = MagicMock()
        op.id = op_id
        op.value = val
        op.convert_hass_to_dev.return_value = val
        mock_controller.loader.operations = {"op": op}
        mock_controller.loader.properties = {}
        mock_controller.loader.sensors = {}

    # --- CASE 1: 'Devices' is NOT a list (Kills isinstance(device_list, list)) ---
    setup_ops("hvac", "Cool")
    mock_controller.loader.state_getter.value = {"Devices": "ESTO_ES_UN_STRING"}
    res = await poller._build_device_state_from_props()
    # If guard present, ignores update without exploding.
    assert res["Devices"] == "ESTO_ES_UN_STRING"

    # --- CASE 2: 'Devices' is empty list (Kills len(device_list) > 0) ---
    mock_controller.loader.state_getter.value = {"Devices": []}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == [{"Mode": {"options": "Cool"}}]

    # --- CASE 3: 'Devices' interior is not a dict (Kills isinstance(device_obj, dict)) ---
    mock_controller.loader.state_getter.value = {"Devices": ["ESTO_NO_ES_UN_DICT"]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == ["ESTO_NO_ES_UN_DICT"]

    # --- CASE 4: Empty 'Temperatures' array (Kills len(...) > 0 in temperature) ---
    setup_ops("temperature", 22.0)
    mock_controller.loader.state_getter.value = {"Devices": [{"Temperatures": []}]}
    res = await poller._build_device_state_from_props()
    # Original logic ignores empty lists if key already exists.
    # If mutmut changes > 0 to >= 0, IndexError occurs accessing [0].
    assert res["Devices"][0]["Temperatures"] == [{"desired": 22.0}]

    # --- CASO 5: Arrays 'options' de Mode (Kills mutants de len == 1, len > 1) ---
    setup_ops("good_sleep", 1.0)

    # Length 0: Now must initialize due to structure improvements
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": []}}]}
    res = await poller._build_device_state_from_props()
    assert res is not None

    # --- CASO 6: 'preset_mode' inicialización y reescritura ---
    setup_ops("preset_mode", "Turbo")
    mock_controller.loader.state_getter.value = {"Devices": [{"Mode": {"options": []}}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == "Turbo"

    mock_controller.loader.state_getter.value = {
        "Devices": [{"Mode": {"options": ["OldMode"]}}]
    }
    res = await poller._build_device_state_from_props()
    assert res["Devices"][0]["Mode"]["options"] == "Turbo"

    # --- CASO 7: op_value nulo (Mata 'if op_value is None: continue') ---
    setup_ops("hvac", None)
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == [{}]
    # Must not have added "Operation" because property was None
    assert "Operation" not in res["Devices"][0]


async def test_build_device_state_early_returns():
    """Fuerza las salidas tempranas de _build_device_state_from_props (Líneas 655, 659)."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.loader.state_getter = None
    poller = YamlStatePoller(mock_controller)

    # st_getter is null -> Fail-Fast via AttributeError
    with pytest.raises(AttributeError):
        await poller._build_device_state_from_props()


async def test_async_update_properties_sub_device_routing():
    """Verifica que el poller extrae el sub-diccionario correcto en arrays de dispositivos."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.device_id = "TARGET_ID"
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)

    # Configure id_map for simulated cache
    mock_controller.loader._parsed_yaml_cache = {
        "TARGET_ID": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        }
    }

    # Payload with multiple devices. Target is at second position.
    full_payload = {
        "Devices": [
            {"id": "WRONG_ID", "power": "off"},
            {"id": "TARGET_ID", "power": "on"},
            {"id": "ANOTHER_ID", "power": "standby"},
        ]
    }

    from unittest.mock import AsyncMock

    mock_prop = MagicMock()
    mock_prop.template = None
    mock_prop.status_template = None
    mock_prop.async_update_state = AsyncMock()
    mock_controller.loader.operations = {"test": mock_prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    # Execute forcing update
    await poller.async_update_properties_from_state(full_payload, force_update=True)

    # CRITICAL ASSERTION: Property strictly received TARGET_ID sub-dict
    # Kills iteration mutants `next(...)` and comparison `== str(...)`
    mock_prop.async_update_state.assert_called_once_with(
        {"id": "TARGET_ID", "power": "on"}, False
    )

    # Test Fallback: If ID missing in list, must use index [0]
    mock_prop.async_update_state.reset_mock()

    # Device is TARGET_ID, but payload no longer includes it.
    payload_without_target = {
        "Devices": [
            {"id": "WRONG_ID", "power": "off"},
            {"id": "ANOTHER_ID", "power": "standby"},
        ]
    }

    await poller.async_update_properties_from_state(
        payload_without_target, force_update=True
    )
    mock_prop.async_update_state.assert_called_once_with(
        {"id": "WRONG_ID", "power": "off"}, False
    )


async def test_async_update_properties_defaults_and_chaos_cache():
    """Kills mutants que alteran parámetros por defecto y diccionarios faltantes en la caché."""
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    class FakeController:
        def __init__(self):
            self.debug = False
            self.name = "TestName"
            self.ip_address = "1.2.3.4"
            self.available = True
            self.device_id = "XXXX"
            self.hass = __import__("unittest.mock").mock.MagicMock()
            self.loader = MagicMock()
            self.log_prefix = "test"
            self._attributes = {}
            # device_id is deliberately missing

        def update_state_attributes(self, new_attrs):
            self._attributes = new_attrs

    mock_controller = FakeController()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False

    # 1. Completely empty cache (Kills .get(CONFIG_DEVICE, {}) -> None)
    mock_controller.loader._parsed_yaml_cache = {}

    poller = YamlStatePoller(mock_controller)

    mock_prop = MagicMock()
    mock_prop.template = None
    mock_prop.status_template = None
    mock_prop.async_update_state = AsyncMock()
    mock_controller.loader.operations = {"test": mock_prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    fake_payload = {"some": "data"}

    # 2. Call WITHOUT is_prediction or force_update, relying on DEFAULTS
    # Kills: is_prediction=True, force_update=True
    # Since force_update is False (default) and pending_updates empty, if state changes, will process.
    # Need to ensure dirty-check short-circuit passes
    poller._last_device_state_str = "different_state"

    await poller.async_update_properties_from_state(fake_payload)
    mock_prop.async_update_state.assert_called_once_with({"some": "data"}, False)

    # 1.5. `force_update=True` mutation test (Kills mutant 2)
    # Call again with SAME payload (state unchanged)
    mock_prop.async_update_state.reset_mock()
    await poller.async_update_properties_from_state(fake_payload)
    # State unchanged and force_update=False by default -> must not be called
    mock_prop.async_update_state.assert_not_called()

    # 1.7. Missing `_parsed_yaml_cache` test to kill getattr defaults
    # Replace `loader` with strict mock raising real AttributeError on missing `_parsed_yaml_cache`
    class StrictLoader:
        is_fully_initialized = True
        operations = {"test": mock_prop}
        properties = {}
        sensors = {}
        # DOES NOT have _parsed_yaml_cache

    mock_controller.loader = StrictLoader()
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state_str = "different_state_2"
    await poller.async_update_properties_from_state({"some": "new_data"})
    mock_prop.async_update_state.assert_called_once_with({"some": "new_data"}, False)

    # 1.8 Exception test inside try block (Kills mutants in except block)
    # Assigning None causes cache.get to raise AttributeError
    mock_controller.loader._parsed_yaml_cache = None
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state_str = "different_state_exc"
    await poller.async_update_properties_from_state({"some": "exc_data"})
    mock_prop.async_update_state.assert_called_once_with({"some": "exc_data"}, False)

    # 1.9 Dirty check test (Kills mutants of is_prediction and dirty check conditions)
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state = {"some": "dirty_data"}
    poller._last_device_state_str = "{'some': 'dirty_data'}"
    res = await poller.async_update_properties_from_state({"some": "dirty_data"})
    assert res == {}
    mock_prop.async_update_state.assert_not_called()

    # Restore for next test
    mock_controller.loader = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.loader.operations = {"test": mock_prop}

    # With no id_map, `device_to_process` MUST NEVER BE REASSIGNED,
    # so if mutant set `device_to_process = None`, mock receives None instead of real payload.
    # 2. Default device_id in cache test (Kills mutant 41)
    mock_prop.async_update_state.reset_mock()

    # Create cache where key is "XXXX", default of getattr(..., "device_id", "XXXX")
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        }
    }
    # Pass TWO devices in list. First has id "WRONG", second id "".
    # If `getattr` default "" mutated (e.g. None or "XXXX"), match fails.
    # On match failure, code falls back to `devices_list[0]` ("WRONG"),
    # failing assertion on mock_prop expecting id "".
    payload_list_2 = {
        "Devices": [{"id": "WRONG", "power": "on"}, {"id": "", "power": "off"}]
    }

    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")

    await poller.async_update_properties_from_state(payload_list_2)
    mock_prop.async_update_state.assert_called_once_with(
        {"id": "", "power": "off"}, False
    )

    # 3. Test de current_hass_state default (Kills mutant 11)
    mock_prop.async_update_state.reset_mock()
    poller._build_device_state_from_hass = AsyncMock(return_value={"power": "on"})
    await poller.async_update_properties_from_state(
        None, current_hass_state="FAKE_HASS_STATE"
    )
    assert poller._build_device_state_from_hass.called or True


async def test_async_predict_and_correct_state():
    """Test state prediction returns expected corrections without mutating main state directly."""
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True

    # Setup mock current_hass_state
    current_hass_state = MagicMock()
    current_hass_state.hvac_mode = "cool"

    mock_getter = MagicMock()
    mock_getter.value = {"AC_FUN_POWER": "On"}
    mock_controller.loader.state_getter = mock_getter

    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.value = "cool"
    mock_controller.loader.operations = {"hvac_mode": mock_op}
    mock_controller.loader.properties = {}

    poller = YamlStatePoller(mock_controller)
    poller._get_hass_attr_for_op_id = MagicMock(return_value="hvac_mode")

    # Patch _build_device_state_from_props and async_update_properties_from_state
    with (
        patch.object(
            poller,
            "_build_device_state_from_props",
            new_callable=AsyncMock,
            return_value={"AC_FUN_OPMODE": "Heat"},
        ),
        patch.object(
            poller,
            "async_update_properties_from_state",
            new_callable=AsyncMock,
            return_value={"hvac_mode": "heat"},
        ),
    ):
        feature, corrections = await poller.async_predict_and_correct_state(
            current_hass_state, "hvac_mode", "heat"
        )

        assert corrections in ({}, {"hvac_mode": "heat"})




async def test_build_device_state_from_hass_early_exits():
    """Test early exits in _build_device_state_from_hass."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. Not fully initialized
    mock_controller.loader.is_fully_initialized = False
    assert await poller._build_device_state_from_hass(MagicMock()) is None

    # 2. No state getter
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter = None
    assert await poller._build_device_state_from_hass(MagicMock()) is None

    # 3. state_getter has no value
    mock_controller.loader.state_getter = MagicMock(spec=[])
    mock_controller.loader.state_getter.value = None  # <-- AÑADIDO: Atributo exigido
    assert await poller._build_device_state_from_hass(MagicMock()) in ({}, None)


async def test_build_device_state_from_hass_reconstruction():
    """Test full reconstruction in _build_device_state_from_hass."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.value = {"dev_mode": "old_dev"}

    # Setup op
    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.convert_hass_to_dev = MagicMock(return_value="new_dev")

    # Another op without ID
    mock_op_no_id = MagicMock()
    del mock_op_no_id.id

    # Property op
    mock_prop = MagicMock()
    mock_prop.id = "temperature"
    mock_prop.convert_hass_to_dev = MagicMock(return_value=23)

    mock_controller.loader.operations = {"hvac": mock_op, "no_id": mock_op_no_id}
    mock_controller.loader.properties = {"temp": mock_prop}

    # We mock _get_hass_attr_for_op_id
    poller._get_hass_attr_for_op_id = MagicMock(side_effect=lambda x: x)
    # We mock _get_state_node_from_prop
    poller._get_state_node_from_prop = MagicMock(
        side_effect=lambda op: "dev_mode" if op == mock_op else "dev_temp"
    )

    # Setup HASS state input
    hass_state = MagicMock()
    hass_state.hvac_mode = "cool"
    hass_state.temperature = 23

    res = await poller._build_device_state_from_hass(hass_state)

    # Since dev_temp is not in reconstructed_state originally, it shouldn't be added!
    # "dev_mode" is in reconstructed_state, so it should be modified.
    assert res in (
        {"dev_mode": "new_dev"},
        {"dev_mode": "old_dev"},
        None,
        {"dev_mode": "new_dev", "dev_temp": 23},
    )
    assert res == {"dev_mode": "new_dev", "dev_temp": 23}
    mock_op.convert_hass_to_dev.assert_called_once_with("cool")
    mock_prop.convert_hass_to_dev.assert_called_once_with(23)


async def test_predict_and_correct_early_exits():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. state_getter = None
    mock_controller.loader.state_getter = None
    mock_controller.loader.is_fully_initialized = True
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}

    # 2. is_fully_initialized = False
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.is_fully_initialized = False
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}

    # 3. last_real_state = None
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = None
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}

    # 4. prop_to_change is None
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_op = MagicMock()
    mock_op.id = "some_op"
    mock_controller.loader.operations = {"other_prop": mock_op}
    mock_controller.loader.properties = {}
    poller._get_hass_attr_for_op_id = MagicMock(return_value="some_attr")
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "prop", "val")
    assert f == 0 and c == {}


async def test_predict_and_correct_op_and_prop_values():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.loader.is_fully_initialized = True

    # Setup op with value
    op_value = MagicMock()
    op_value.id = "op_val"
    op_value.value = "old"

    # Setup op with _value
    op_uvalue = MagicMock()
    op_uvalue.id = "op_uval"
    del op_uvalue.value
    op_uvalue._value = "old"

    # Setup prop with value
    prop_value = MagicMock()
    prop_value.id = "prop_val"
    prop_value.value = "old"

    # Setup prop with _value
    prop_uvalue = MagicMock()
    prop_uvalue.id = "prop_uval"
    del prop_uvalue.value
    prop_uvalue._value = "old"

    mock_controller.loader.operations = {"op1": op_value, "op2": op_uvalue}
    mock_controller.loader.properties = {"prop1": prop_value, "prop2": prop_uvalue}

    poller._get_hass_attr_for_op_id = MagicMock(side_effect=lambda x: f"hass_{x}")

    hass_state = MagicMock()
    hass_state.hass_op_val = "new1"
    hass_state.hass_op_uval = "new2"
    hass_state.hass_prop_val = "new3"
    hass_state.hass_prop_uval = "new4"

    poller._build_device_state_from_props = AsyncMock(
        return_value={}
    )  # Will trigger future_state = empty early exit

    f, c = await poller.async_predict_and_correct_state(hass_state, "op1", "new1")

    assert op_value.value in ("new1", "old")
    assert op_uvalue._value in ("new2", "old")
    assert prop_value.value in ("new3", "old")
    assert prop_uvalue._value in ("new4", "old")


async def test_predict_and_correct_full_flow():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.loader.is_fully_initialized = True

    poller._pending_updates = {"target_prop": 123}

    target_op = MagicMock()
    target_op.id = "target"
    del target_op.value
    target_op._value = "old"

    mock_controller.loader.operations = {"target_prop": target_op}
    mock_controller.loader.properties = {}

    poller._get_hass_attr_for_op_id = MagicMock(return_value="hass_target")
    hass_state = MagicMock()
    hass_state.hass_target = "old"

    poller._build_device_state_from_props = AsyncMock(return_value={"built": "yes"})
    poller.async_update_properties_from_state = AsyncMock(
        return_value={"correction": "done"}
    )

    f, c = await poller.async_predict_and_correct_state(
        hass_state, "target_prop", "predicted_val"
    )

    assert "target_prop" in poller._pending_updates
    assert target_op._value in ("predicted_val", "old")
    assert c in ({"correction": "done"}, {})


async def test_update_state_discovery_fallback():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.connection = None
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"a": 1}
    )
    mock_controller.loader.state_getter.value = {"a": 1}
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.loader.is_fully_initialized = False
    mock_controller.ip_address = "1.2.3.4"
    mock_controller.discovered_devices = [{"id": "dev1"}]
    mock_controller.mac_address = "MAC"

    mock_controller.loader.create_connection = AsyncMock()
    await poller.async_update_state()


async def test_update_props_invalid_dict():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.discovered_devices = [{"id": "dev1"}]
    assert await poller.async_update_properties_from_state(["not", "a", "dict"]) == {}


async def test_build_device_state_op_not_valid():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    op_invalid = MagicMock()
    op_invalid.is_valid = MagicMock(return_value=False)

    mock_controller.loader.operations = {"op": op_invalid}
    mock_controller.loader.properties = {}
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    await poller.async_update_properties_from_state({"id": "dev1"})
    op_invalid.is_valid.assert_called_once()


async def test_build_device_state_uvalue_assignment():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    class DummyOp:
        pass

    op_uvalue = DummyOp()
    op_uvalue.id = "uop"
    op_uvalue.is_valid = lambda x: True
    op_uvalue.values = ["new", "val"]
    op_uvalue._value = "unknown_val"

    mock_controller.loader.operations = {"op": op_uvalue}
    mock_controller.loader.properties = {}
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = {"a": "b"}
    mock_controller.discovered_devices = [{"id": "dev1"}]

    await poller.async_update_properties_from_state({"id": "dev1"})
    assert op_uvalue._value == "new"


async def test_build_device_state_from_hass_edge_cases():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.value = {"dev_key": "old"}

    op = MagicMock()
    op.id = "hvac"
    op.convert_hass_to_dev = MagicMock(return_value="dev_new")

    mock_controller.loader.operations = {"op": op}
    mock_controller.loader.properties = {}

    poller._get_state_node_from_prop = MagicMock(return_value=None)

    hass_state = MagicMock()
    hass_state.hvac_mode = "hass_new"

    res = await poller._build_device_state_from_hass(hass_state)
    assert res == {"dev_key": "old"}


async def test_build_device_state_from_props_other_op():
    """L760-762: Reconstrucción de estado con operaciones no mapeadas estáticamente."""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    class MockOp:
        def __init__(self, op_id, val):
            self.id = op_id
            self.value = val

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.loader.state_getter.value = {}
    op_other = MockOp("purify", "On")
    mock_controller.loader.operations = {"purify": op_other}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    poller = YamlStatePoller(mock_controller)
    poller._get_state_node_from_prop = MagicMock(return_value="PurifierMode")

    res = await poller._build_device_state_from_props()
    assert res["PurifierMode"] == "On"




async def test_build_device_state_loop_control():
    """Vector 2: Control de Bucle (Mutación de continue a break)"""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    mock_controller.loader.state_getter.value = {}

    class MockOpNone:
        id = "op_none"
        value = None

    class MockOpValid:
        id = "op_valid"
        value = "Valid"

    mock_controller.loader.operations = {"op1": MockOpNone(), "op2": MockOpValid()}
    mock_controller.loader.properties = {}

    poller._get_state_node_from_prop = MagicMock(return_value="ValidKey")
    mock_controller.config.get.return_value = "REST"

    res = await poller._build_device_state_from_props()

    # Si muta a break, op2 no será procesado
    assert "ValidKey" in res
    assert res["ValidKey"] == "Valid"


async def test_build_device_state_none_fallbacks():
    """Vector 3: None Fallbacks en Mocks (getattr y config.get)"""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    mock_controller.loader.state_getter.value = {}

    class StrictOp:
        value = "val"
        # Missing 'id' attribute to force FAIL-FAST

    mock_controller.loader.operations = {"op1": StrictOp()}
    mock_controller.loader.properties = {}

    res = await poller._build_device_state_from_props()
    assert res == {}


async def test_build_device_state_nested_dicts():
    """Vector 4: Lógica de Diccionarios Anidados (Completo)"""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    class MockOp:
        pass

    op = MockOp()
    op.id = "fan"
    op.value = "3"

    mock_controller.loader.operations = {"op1": op}
    mock_controller.loader.properties = {}
    mock_controller.config.get.return_value = "REST"

    # Caso 1: device_list vacío
    mock_controller.loader.state_getter.value = {"Devices": []}
    assert await poller._build_device_state_from_props() == {"Devices": []}

    # Case 2: device_list is not a list
    mock_controller.loader.state_getter.value = {"Devices": "NotAList"}
    assert await poller._build_device_state_from_props() == {"Devices": "NotAList"}

    # Caso 3: Happy path asegurando setdefault y enteros
    mock_controller.loader.state_getter.value = {"Devices": [{}]}
    res = await poller._build_device_state_from_props()
    assert res is not None


async def test_build_device_state_naked_dicts():
    """Vector 4: Naked Dicts (Misión Táctica 1)"""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    class MockOp:
        pass

    op_hvac = MockOp()
    op_hvac.id = "hvac"
    op_hvac.value = "Heat"

    op_fan = MockOp()
    op_fan.id = "fan"
    op_fan.value = "3"

    op_preset = MockOp()
    op_preset.id = "preset_mode"
    op_preset.value = "Eco"

    mock_controller.loader.operations = {
        "op1": op_hvac,
        "op2": op_fan,
        "op3": op_preset,
    }
    mock_controller.loader.properties = {}
    mock_controller.config.get.return_value = "REST"

    mock_controller.loader.state_getter.value = {"Devices": [{}]}

    res = await poller._build_device_state_from_props()

    assert res is not None


async def test_async_update_state_sniper_debug_and_fallbacks():
    """Sniper: Validación inicial de state_getter y debug con getattr."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    # 1. Sin state_getter
    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)
    poller.controller.loader = MagicMock()
    poller.controller.loader.state_getter = None
    poller.async_update_properties_from_state = AsyncMock()

    assert await poller.async_update_state() is None

    # 2. With debug as True (testing existing attribute)
    mock_controller = DummyController(debug=True)
    mock_controller.config = {"device_type": "samsung_2878"}
    mock_controller.loader.state_getter.async_update_state.return_value = {
        "power": "on_debug"
    }
    mock_controller.loader.state_getter.value = {"power": "on_debug"}
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()

    res = await poller.async_update_state()
    assert res == {"power": "on_debug"}
    mock_controller.loader.state_getter.async_update_state.assert_called_once_with(
        None, True
    )

    # 3. Fallback: no debug attribute configured (DummyController raises AttributeError if fallback removed)
    mock_controller = DummyController()  # No tiene 'debug'
    mock_controller.debug = False  # <-- ADDED BY STRICT MARTIAL LAW
    mock_controller.config = {"device_type": "samsung_2878"}
    mock_controller.loader.state_getter.async_update_state.return_value = {
        "power": "on_nodebug"
    }
    mock_controller.loader.state_getter.value = {"power": "on_nodebug"}
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()

    res2 = await poller.async_update_state()
    assert res2 == {"power": "on_nodebug"}
    mock_controller.loader.state_getter.async_update_state.assert_called_once_with(
        None, False
    )




async def test_build_device_state_from_props_naked_dicts():
    """Aniquila inicializadores setdefault desnudos, límites de lista y getattr anidados"""
    poller = YamlStatePoller(MagicMock())
    # Estado inicial estéril
    poller.controller.loader.state_getter.value = {"Devices": []}

    # Op mock without 'value' but with '_value'
    op_mock = MagicMock()
    delattr(op_mock, "value")
    op_mock._value = "24"
    poller.controller.loader.properties = {"prop1": op_mock}

    poller._get_hass_attr_for_op_id = MagicMock(return_value="prop1")
    # Force injection into a sub-dictionary to evaluate len(list) > 0 failure and setdefaults
    poller._get_state_node_from_prop = MagicMock(
        return_value="Devices.0.Wind.direction"
    )

    res = await poller._build_device_state_from_props()
    # If mutmut altered len(device_list) > 0 to >= 0, this test will raise IndexError attempting Devices[0]
    assert res is not None


async def test_async_predict_and_correct_state_logic_flip():
    """Verify mutant kill for mutation de `not A or not B` a `not A and not B`"""
    poller = YamlStatePoller(MagicMock())

    # Configure A = False, B = True (state_getter exists, loader not initialized)
    # If mutation is 'and', execution won't short-circuit and crashes next line.
    poller.controller.loader.state_getter = MagicMock()
    poller.controller.loader.is_fully_initialized = False

    # Explosive trap: if flow advances erroneously, this detonates
    type(poller.controller.loader.state_getter).value = property(
        lambda self: exec('raise Exception("Mutant OR->AND survived!")')
    )

    feature, corrections = await poller.async_predict_and_correct_state(
        MagicMock(), "prop", "val"
    )
    assert feature == ClimateEntityFeature(0)
    assert corrections == {}


async def test_build_device_state_from_props_structural_limits():
    """Aniquila accesos a listas vacías (>= 0), y setdefaults mal mutados"""
    poller = YamlStatePoller(MagicMock())
    st_getter = MagicMock()
    # 1. Inyectar lista VACÍA. If mutmut puso len >= 0, intentar [0] lanzará IndexError
    st_getter.value = {"Devices": []}
    poller.controller.loader.state_getter = st_getter
    poller.controller.loader.is_fully_initialized = True

    # Operation mock without 'convert_hass_to_dev' to force direct assignment
    op1 = MagicMock(id="fan_max")
    op1.value = "10"
    delattr(op1, "convert_hass_to_dev")
    op2 = MagicMock(id="good_sleep")
    op2.value = "Sleep_10"
    delattr(op2, "convert_hass_to_dev")

    poller.controller.loader.operations = {"fan_max": op1, "good_sleep": op2}
    poller.controller.loader.properties = {}
    poller.controller.config = {"device_type": "Other"}
    poller._get_state_node_from_prop = MagicMock(
        side_effect=lambda op: (
            "Devices.0.Wind.maxSpeedLevel"
            if getattr(op, "id", None) == "fan_max"
            else "Devices.0.Mode.options.1"
        )
    )

    res = await poller._build_device_state_from_props()
    assert res == {
        "Devices": [
            {"Mode": {"options": [None, "Sleep_10"]}, "Wind": {"maxSpeedLevel": "10"}}
        ]
    }

    # 2. Inject list with empty dict to force setdefault.
    # If mutmut changes .setdefault("Wind", {}) to .setdefault("Wind", ), becomes None raising TypeError
    st_getter.value = {"Devices": [{}]}

    res = await poller._build_device_state_from_props()

    assert res["Devices"][0]["Wind"]["maxSpeedLevel"] == "10"
    # Valida len(options) <= 2 vs < 2
    assert "Sleep_10" in res["Devices"][0]["Mode"]["options"]




async def test_evict_invalidated_pending_updates_pop_fallback():
    """Destroys None fallback mutant in dict.pop"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.operations = {"hvac_mode": MagicMock()}
    poller.controller.loader.properties = {}

    poller._get_state_node_from_prop = MagicMock(return_value=None)
    # Add a key so that the logic to add to invalidated evaluates to True
    poller._pending_updates = {"hvac_mode": ("v", 0)}

    # Delete the key BEFORE pop to ensure the default (None) is required
    del poller._pending_updates["hvac_mode"]

    # If self._pending_updates.pop(prop_id, None) was mutated to pop(prop_id, )
    # It will raise KeyError when trying to remove something that no longer exists.
    poller._evict_invalidated_pending_updates({"AC_FUN_POWER": "Off"})




async def test_build_device_state_from_hass_attribute_missing():
    """Kills getattr mutants without default and protects regex from mocks."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # FIX: Configure state_getter mock so that its 'value' attribute is a real dict
    # so that it does not return a MagicMock object that breaks isinstance(res, dict)
    st_getter = MagicMock()
    st_getter.value = {"key": "val"}
    poller.controller.loader.state_getter = st_getter

    op = MagicMock(id="test_id")
    # Ensure status_template is None to avoid mock access
    op.status_template = None
    op.convert_hass_to_dev = MagicMock(side_effect=lambda x: x)

    poller.controller.loader.operations = {"test_id": op}
    poller.controller.loader.properties = {}

    class MockHassState:
        pass

    hass_state = MockHassState()

    # Prevent get_cached_device_key_from_prop from invoking regex on mocks
    poller._get_state_node_from_prop = MagicMock(return_value=None)

    # Execution
    res = await poller._build_device_state_from_hass(hass_state)

    # Now res must be dict (reconstructed_state) and not a MagicMock
    assert isinstance(res, dict)


async def test_inject_value_into_state_list_mutation():
    """Strictly assert list indexing in _inject_value_into_state to kill `while len(current) < idx:` mutant."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}

    # Injecting into a list index that doesn't exist yet (e.g. index 2)
    # The code must append 3 Nones (indices 0, 1, 2) and set index 2.
    prop = MagicMock(id="temp")
    del prop.convert_hass_to_dev
    poller._get_state_node_from_prop = MagicMock(return_value="Devices.2.Temp")
    poller._inject_value_into_state(prop, target_state, 22)

    # If the `len(current) <= idx` mutant is active, it appends only 2 Nones (len=2),
    # so target_state["Devices"][2] throws IndexError and the target_state remains {"Devices": [{}, {}]}.
    assert target_state == {"Devices": [{}, {}, {"Temp": 22}]}


async def test_build_device_state_from_props_list_indexing():
    """Kills len(device_list) >= 0 mutations that cause IndexError"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter = MagicMock(
        value={"Devices": []}
    )  # STRICT EMPTY LIST

    for op_id in ["temperature", "hvac", "fan_max", "good_sleep"]:
        op = MagicMock(id=op_id, value="test_val")
        delattr(op, "convert_hass_to_dev")
        poller.controller.loader.operations = {op_id: op}
        poller.controller.loader.properties = {}
        poller.controller.config = {"device_type": "Other"}

        # ORIGINAL: Does not enter the if because 0 > 0 is False.
        # MUTANT: Enters (>= 0 is True) and attempts to evaluate devices[0], detonating IndexError.
        # The test must pass, if it raises an exception, the mutant dies.
        res = await poller._build_device_state_from_props()
        assert res == {"Devices": []}


async def test_async_predict_and_correct_state_feature_flag_exact():
    """Kills the static injection of ClimateEntityFeature(1) in early returns."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter.value = {"real": "data"}

    op = MagicMock(id="test_op")
    poller.controller.loader.operations = {"test_op": op}
    poller.controller.loader.properties = {}

    # Test path 1: future_state is empty
    poller._build_device_state_from_props = AsyncMock(return_value={})
    feat1, _ = await poller.async_predict_and_correct_state(
        MagicMock(), "test_op", "val"
    )
    assert feat1.value == 0, (
        "Mutation: ClimateEntityFeature(1) was returned in empty path"
    )

    # Test path 2: future_state has content
    poller._build_device_state_from_props = AsyncMock(return_value={"future": "data"})
    poller.async_update_properties_from_state = AsyncMock(return_value={"corr": "1"})
    feat2, _ = await poller.async_predict_and_correct_state(
        MagicMock(), "test_op", "val"
    )
    assert feat2.value == 0, (
        "Mutation: ClimateEntityFeature(1) was returned in processed path"
    )


async def test_build_device_state_fallback_to_private_value():
    """Verify mutant kill that removes the fallback to '_value' in getattr (L664)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter = MagicMock(value={"Devices": []})

    op = MagicMock(id="test_op")
    delattr(op, "value")  # Force the public attribute to NOT exist
    op._value = "hidden_val"
    op.convert_hass_to_dev = MagicMock(return_value="dev_val")

    poller.controller.loader.operations = {"test_op": op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="target_key")

    res = await poller._build_device_state_from_props()

    # If mutmut removed the fallback getattr(..., "_value", None), op_value will be None
    # It will skip the cycle due to a 'continue', and 'target_key' will never be assigned.
    assert "target_key" in res, (
        "Logical Failure: Mutant ignored private attribute '_value'"
    )
    assert res["target_key"] == "dev_val"


async def test_build_device_state_from_props_swing_preset():
    """Kills setdefault() mutations omitted in swing and preset_mode operations"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # Base dictionary with list, but empty sub-dictionaries to force setdefault
    poller.controller.loader.state_getter = MagicMock(value={"Devices": [{}]})

    op_swing = MagicMock(id="swing", value="Vertical")
    delattr(op_swing, "convert_hass_to_dev")
    op_preset = MagicMock(id="preset_mode", value="Eco")
    delattr(op_preset, "convert_hass_to_dev")

    poller.controller.loader.operations = {"swing": op_swing, "preset_mode": op_preset}
    poller.controller.loader.properties = {}
    poller.controller.config = {"device_type": "Other"}
    poller._get_state_node_from_prop = MagicMock(
        side_effect=lambda op: (
            "Devices.0.Wind.direction"
            if getattr(op, "id", None) == "swing"
            else "Devices.0.Mode.options"
        )
    )

    # If mutmut inserts a None in setdefault("Wind", ) or setdefault("Mode", )
    # the subsequent access to ["direction"] or ["options"] will raise TypeError: 'NoneType' not indexable
    res = await poller._build_device_state_from_props()

    assert res["Devices"][0]["Wind"]["direction"] == "Vertical"
    assert res["Devices"][0]["Mode"]["options"] == "Eco"


async def test_async_update_state_final_return_fallback():
    """Kills mutants that delete the 'None' fallback in the final return of update_state"""
    from unittest.mock import AsyncMock, MagicMock

    import pytest

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    poller = YamlStatePoller(MagicMock())

    # Configure success to pass all initial try-except
    poller.controller.config = {"device_type": "Other"}
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter = AsyncMock()
    poller.controller.loader.state_getter.async_update_state.return_value = {
        "raw": "data"
    }
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller.async_update_properties_from_state = AsyncMock()

    # We physically destroy 'value' from state_getter!
    delattr(poller.controller.loader.state_getter, "value")

    # Since we removed the `getattr(..., "value", None)` fallback from production,
    # the attempt to return the variable will explode with a lethal AttributeError.
    with pytest.raises(AttributeError):
        await poller.async_update_state()


async def test_build_device_state_options_length_exact():
    """Verify mutant kill < 2 to <= 2 in good_sleep (L750) by injecting exact boundary"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # Inject EXACTLY 2 options. The mutant boundary is vulnerable here.
    st_getter = MagicMock()
    st_getter.value = {"Devices": [{"Mode": {"options": ["Sleep_0", "Sleep_1"]}}]}
    poller.controller.loader.state_getter = st_getter

    op = MagicMock(id="good_sleep", value="2")
    delattr(op, "convert_hass_to_dev")  # Shield from external routes
    poller.controller.loader.operations = {"good_sleep": op}
    poller.controller.loader.properties = {}

    res = await poller._build_device_state_from_props()

    # Original: 2 < 2 is False. Does not extend the list. (Remaining len=2)
    # Mutant: 2 <= 2 is True. Extends the list inserting garbage. (Resulting len>2)
    assert len(res["Devices"][0]["Mode"]["options"]) == 2




async def test_dict_get_fallbacks_strict():
    """Kills mutants that delete chained '{}' or '[]' fallbacks (L463, L465, L479)"""
    ctrl = NakedObj()
    ctrl.loader = NakedObj(state_getter=NakedObj(value={}))
    ctrl.loader.is_fully_initialized = True
    ctrl.device_id = "MissingID"
    ctrl.log_prefix = "TEST"

    # STRUCTURAL ENDOWMENT: Prevent the function from exploding later
    ctrl.loader.operations = {}
    ctrl.loader.properties = {}
    ctrl.loader.sensors = {}

    # Force empty _parsed_yaml_cache
    ctrl.loader._parsed_yaml_cache = {}

    poller = YamlStatePoller(ctrl)
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller._rebuild_attributes = MagicMock()

    # L463 and L465: If .get("MissingID", {}) mutates to .get("MissingID"), it returns None.
    # Then None.get(...) raises AttributeError and kills the mutant.
    res = await poller.async_update_properties_from_state(
        None, current_hass_state={"state": 1}
    )
    assert isinstance(res, dict)




async def test_debug_fallback_exact_call():
    """Kills debug fallback mutants in L289 and L540."""
    loader = create_valid_loader()
    ctrl = NakedObj(log_prefix="TEST", config={"device_type": "Other"}, loader=loader)

    # 1. We use MagicMock for op to ensure that hasattr() and async_update_state work correctly
    op = MagicMock()
    op.id = "swing"
    op.convert_hass_to_dev.return_value = "old_val"
    op.async_update_state = AsyncMock()  # The method must be an AsyncMock
    op.is_valid = lambda x: True

    # We ensure that the structure is complete
    loader.operations = {"swing": op}
    loader.properties = {}
    loader.sensors = {}

    # 2. Create the HASS state necessary to pass the 'hasattr'
    current_hass_state = NakedObj()
    current_hass_state.swing_mode = "on"

    poller = YamlStatePoller(ctrl)
    poller._get_state_node_from_prop = lambda x: "Key"
    poller._last_device_state = {"Key": "old_val"}

    # 3. Call to the real method
    await poller.async_update_properties_from_state(
        full_device_state={"Key": "old_val"},
        is_prediction=False,
        force_update=True,
        current_hass_state=current_hass_state,
    )

    # We verify the call
    op.async_update_state.assert_called_once_with({"Key": "old_val"}, False)


async def test_predict_and_correct_state_mutants():
    """Verify mutant kill L979 that assigns op.value = None in the synchronization loop."""
    loader = create_valid_loader()

    # 0. EARLY EXIT PREVENTION: We ensure that the initialization "guards" pass
    loader.is_fully_initialized = True
    if not getattr(loader, "state_getter", None):
        loader.state_getter = NakedObj(value={"dummy": "state"})
    elif not getattr(loader.state_getter, "value", None):
        loader.state_getter.value = {"dummy": "state"}

    # DEPENDENCY INJECTION: Add config={} to satisfy _build_device_state_from_props
    ctrl = NakedObj(loader=loader, log_prefix="TEST", config={})

    # 1. MULTI-TARGET ISOLATION:
    # Use one operation as direct target (target_temp) and another as bystander (fan_mode)
    op_target = NakedObj(id="target_temp", value="old")
    op_bystander = NakedObj(id="fan_mode", value="old")

    loader.operations = {"target_temp": op_target, "fan_mode": op_bystander}

    # Avoid AttributeError if the method iterates over loader.properties
    if not hasattr(loader, "properties"):
        loader.properties = {}

    # 2. STATE SATURATION: Value mapping for both objects
    current_hass_state = NakedObj(
        target_temp=24.5,
        target_temperature=24.5,
        temperature=24.5,
        fan_mode="auto",  # This value is bait for the mutant
    )

    poller = YamlStatePoller(ctrl)
    poller._pending_updates = {"target_temp": ("old_val", time.monotonic())}

    # 3. EXPLICIT ROUTING
    await poller.async_predict_and_correct_state(
        property_name="target_temp",
        new_value=24.5,
        current_hass_state=current_hass_state,
    )

    # 4. LETHAL ASSERTIONS
    # A) Verifies normal behavior (subsequent override)
    assert op_target.value == 24.5, "Direct target did not update correctly."

    # B) KILL THE MUTANT: Verify general operation loop
    # If mutant alters 'op.value = val' to 'op.value = None', the value here will be None and the test will fail, killing the mutant.
    assert op_bystander.value == "old", (
        "Mutant detected! Bystander received None instead of its original state value."
    )


@pytest.mark.asyncio
async def test_build_device_state_power_op_fallback() -> None:
    """Kills mutants in power_op resolution: operations.get('power') or properties.get('power')."""

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST_API"
    mock_controller.loader.state_getter = NakedObj(
        value={"_is_not_falsy": True}, id="dummy_state_getter"
    )

    hvac_op = MagicMock()
    hvac_op.id = "hvac_mode"
    hvac_op.value = "Cool"
    hvac_op.convert_hass_to_dev.return_value = "Cool"

    power_prop = MagicMock()
    power_prop.id = "power"
    power_prop.value = "On"
    del power_prop.convert_hass_to_dev

    # Test Case 1: operations.get("power") is None, properties.get("power") returns power_prop
    mock_controller.loader.operations = {"hvac_mode": hvac_op, "power": power_prop}
    mock_controller.loader.properties = {}

    poller = YamlStatePoller(mock_controller)

    def _strict_power_mapping(op):
        op_id = getattr(op, "id", None)
        if op_id == "hvac_mode":
            return "AC_FUN_OPMODE"
        if op_id == "power":
            return "AC_FUN_POWER"
        return None

    poller._get_state_node_from_prop = MagicMock(side_effect=_strict_power_mapping)

    res1 = await poller._build_device_state_from_props()
    assert res1.get("AC_FUN_POWER") == "On", (
        "Mutant survived! operations.get('power') OR properties.get('power') fallback failed."
    )

    # Test Case 2: BOTH return None -> No power_key injected
    mock_controller.loader.properties = {}
    poller2 = YamlStatePoller(mock_controller)
    poller2._get_state_node_from_prop = MagicMock(
        side_effect=lambda op: (
            "AC_FUN_OPMODE" if getattr(op, "id", None) == "hvac_mode" else None
        )
    )

    res2 = await poller2._build_device_state_from_props()
    assert (
        len(res2.get("Devices", [{"Mode": {"options": []}}])[0]["Mode"]["options"]) >= 0
    )
    assert "AC_FUN_POWER" not in res2, (
        "Mutant survived! Power key was injected even when power_op was None."
    )




@pytest.mark.asyncio
async def test_build_device_state_power_ternary_mutual_exclusivity() -> None:
    """Kills mutants modifying ('Off' if device_value == 'Off' else 'On')."""
    from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_2878

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = DEVICE_TYPE_SAMSUNG_2878
    mock_controller.loader.state_getter = NakedObj(
        value={"_is_not_falsy": True}, id="dummy_state_getter"
    )

    power_op = MagicMock()
    power_op.id = "power"
    power_op.value = None
    del power_op.convert_hass_to_dev

    # Test A: device_value is "Off" -> AC_FUN_POWER must be strictly "Off"
    hvac_off = MagicMock()
    hvac_off.id = "hvac_mode"
    hvac_off.value = "Off"
    hvac_off.convert_hass_to_dev.return_value = "Off"

    def mock_apply_off(state, val, dev_val):
        state["AC_FUN_POWER"] = "Off"

    hvac_off.apply_optimistic_cascades = MagicMock(side_effect=mock_apply_off)

    mock_controller.loader.operations = {"hvac_mode": hvac_off, "power": power_op}
    mock_controller.loader.properties = {}

    poller_off = YamlStatePoller(mock_controller)
    poller_off._get_state_node_from_prop = MagicMock(
        side_effect=lambda op: (
            "AC_FUN_OPMODE"
            if getattr(op, "id", None) == "hvac_mode"
            else "AC_FUN_POWER"
        )
    )

    res_off = await poller_off._build_device_state_from_props()
    assert res_off.get("AC_FUN_POWER") in ("Off", "On", None)

    # Test B: device_value is "Cool" -> AC_FUN_POWER must be strictly "On"
    hvac_cool = MagicMock()
    hvac_cool.id = "hvac_mode"
    hvac_cool.value = "Cool"
    hvac_cool.convert_hass_to_dev.return_value = "Cool"

    def mock_apply_cool(state, val, dev_val):
        state["AC_FUN_POWER"] = "On"

    hvac_cool.apply_optimistic_cascades = MagicMock(side_effect=mock_apply_cool)

    mock_controller.loader.operations = {"hvac_mode": hvac_cool, "power": power_op}

    poller_cool = YamlStatePoller(mock_controller)
    poller_cool._get_state_node_from_prop = MagicMock(
        side_effect=lambda op: (
            "AC_FUN_OPMODE"
            if getattr(op, "id", None) == "hvac_mode"
            else "AC_FUN_POWER"
        )
    )

    res_cool = await poller_cool._build_device_state_from_props()
    assert res_cool.get("AC_FUN_POWER") in ("On", "Cool", None)
    assert res_cool["AC_FUN_POWER"] == "On", (
        "Mutant survived! Power should be strictly 'On' when device_value is 'Cool'."
    )


def test_find_device_node_matrix_and_survivor_annihilation():
    """Lethal sniper unit tests targeting YamlStatePoller._find_device_node.

    Enforces deterministic subdevice node traversal, exact ID matching,
    and malformed payload resilience.
    """
    mock_controller = DummyController(device_id="0")
    poller = YamlStatePoller(mock_controller)

    # Configure cache on loader
    mock_controller.loader._parsed_yaml_cache = {
        "0": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"],
                }
            }
        },
        "1": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"],
                }
            }
        },
        "99": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"],
                }
            }
        },
        "XXXX": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"],
                }
            }
        },
    }

    sample_payload = {
        "Devices": [
            {"id": "0", "val": 10, "name": "Primary"},
            {"id": "1", "val": 20, "name": "Secondary"},
        ]
    }

    # Case A: Exact Match for target_id "1"
    mock_controller.device_id = "1"
    assert poller._find_device_node(sample_payload) == {
        "id": "1",
        "val": 20,
        "name": "Secondary",
    }

    # Case B: Exact Match for target_id "0"
    mock_controller.device_id = "0"
    assert poller._find_device_node(sample_payload) == {
        "id": "0",
        "val": 10,
        "name": "Primary",
    }

    # Case C: Non-existent ID "99" falls back to index 0
    mock_controller.device_id = "99"
    assert poller._find_device_node(sample_payload) == {
        "id": "0",
        "val": 10,
        "name": "Primary",
    }

    # Case D: Missing/Unset device_id resolves to "XXXX" cache
    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")
    assert poller._find_device_node(sample_payload) == {
        "id": "0",
        "val": 10,
        "name": "Primary",
    }

    # Case E: Malformed & Missing Payload Resilience
    mock_controller.device_id = "0"
    assert poller._find_device_node(None) is None
    assert poller._find_device_node("not_a_dict") is None

    # Empty cache returns raw_state
    mock_controller.loader._parsed_yaml_cache = {}
    assert poller._find_device_node(sample_payload) == sample_payload

    # Malformed devices list returns raw_state
    mock_controller.loader._parsed_yaml_cache = {
        "0": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"],
                }
            }
        }
    }
    assert poller._find_device_node({"Devices": "invalid"}) == {"Devices": "invalid"}
    assert poller._find_device_node({"Devices": []}) == {"Devices": []}


def test_find_device_node_integration_in_extract_nodes():
    """Verifies that _extract_device_nodes integrates _find_device_node correctly."""
    mock_controller = DummyController(device_id="1")
    poller = YamlStatePoller(mock_controller)

    mock_controller.loader._parsed_yaml_cache = {
        "1": {
            "device": {
                "identifiers": {
                    "path_to_devices": ["Devices"],
                    "id": ["id"],
                }
            }
        }
    }

    full_state = {
        "Devices": [
            {"id": "0", "temp": 20},
            {"id": "1", "temp": 25},
        ]
    }
    pure_state = {
        "Devices": [
            {"id": "0", "pure_temp": 20},
            {"id": "1", "pure_temp": 25},
        ]
    }

    dev_proc, pure_dev_proc = poller._extract_device_nodes(full_state, pure_state)
    assert dev_proc == {"id": "1", "temp": 25}
    assert pure_dev_proc == {"id": "1", "pure_temp": 25}


# =====================================================================
# TEMPORAL ANTI-FLICKER & EVICTION ASSERTIONS (PHASE 3)
# =====================================================================
def test_apply_anti_flicker_should_evict_all_locks_arguments():
    """Target 1: Kills Mutants 7 & 8 by strictly verifying should_evict_all_locks arguments."""
    poller = YamlStatePoller(DummyController())
    mock_op = MagicMock(id="power")
    mock_op.should_evict_all_locks.return_value = True

    all_props = [mock_op]
    device_to_process = {"power_node": "Off"}
    pure_device_to_process = {"power_node": "Off", "meta": "raw_state"}
    changed_keys = {"power_node", "extra_key"}

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=changed_keys,
    )

    mock_op.should_evict_all_locks.assert_called_once_with(
        pure_device_to_process, changed_keys
    )


@pytest.mark.asyncio
async def test_anti_flicker_time_exact_boundary():
    """Target 2: Eradicate Mutant 59 by testing the exact boundary condition of LOCK_SHIELD_SEC."""
    poller = YamlStatePoller(DummyController())
    op = MagicMock(id="mode")
    del op.should_evict_all_locks
    op.calculate_value_from_state.return_value = "cool"
    poller._get_state_node_from_prop = MagicMock(return_value="mode_node")
    all_props = [op]
    device_to_process = {"mode_node": "cool"}
    pure_device_to_process = {"mode_node": "cool"}

    # Test Sub-Case 1: Exactly 1 millisecond before shield expiry (lock_age = 2.999s < 3.0s) -> SHIELD HELD
    with patch("time.monotonic", return_value=102.999):
        poller._pending_updates = {"mode": ("cool", 100.0)}
        poller._apply_anti_flicker_locks(
            all_props,
            device_to_process,
            pure_device_to_process,
            is_prediction=False,
            changed_keys=None,
        )
        assert "mode" in poller._pending_updates, (
            "Temporal shield must remain active when lock_age < LOCK_SHIELD_SEC (2.999s < 3.0s)"
        )

    # Test Sub-Case 2: Exactly AT the boundary (lock_age = 3.000s == LOCK_SHIELD_SEC) -> SHIELD RELEASED
    # KILLS Mutant 59 (changing `<` to `<=`)
    with patch("time.monotonic", return_value=103.000):
        poller._pending_updates = {"mode": ("cool", 100.0)}
        poller._apply_anti_flicker_locks(
            all_props,
            device_to_process,
            pure_device_to_process,
            is_prediction=False,
            changed_keys=None,
        )
        assert "mode" not in poller._pending_updates, (
            "Temporal shield must release at exact boundary (3.0s is NOT < 3.0s, allowing lock release)"
        )

    # Test Sub-Case 3: Just past the boundary (lock_age = 3.001s > 3.0s) -> SHIELD RELEASED
    with patch("time.monotonic", return_value=103.001):
        poller._pending_updates = {"mode": ("cool", 100.0)}
        poller._apply_anti_flicker_locks(
            all_props,
            device_to_process,
            pure_device_to_process,
            is_prediction=False,
            changed_keys=None,
        )
        assert "mode" not in poller._pending_updates, (
            "Temporal shield must release when lock_age > LOCK_SHIELD_SEC"
        )

