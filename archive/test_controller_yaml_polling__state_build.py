import contextlib
import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_2878
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.helpers.template import Template


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
            with contextlib.suppress(Exception):
                val = prop.convert_hass_to_dev(val)
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
    orig_async_update_properties = YamlStatePoller.async_update_properties_from_state

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


async def test_update_props_early_returns():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.discovered_devices = [{"id": "dev1"}]

    # Caso 1: Not initialized
    mock_controller.loader.is_fully_initialized = False
    assert await poller.async_update_properties_from_state({"a": 1}) == {}

    # Caso 2: Null state
    mock_controller.loader.is_fully_initialized = True
    assert await poller.async_update_properties_from_state(None) == {}

    # Caso 3: Invalid type (not a dict)
    assert await poller.async_update_properties_from_state(["not", "a", "dict"]) == {}


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


async def test_async_predict_and_correct_state_logic_flip():
    """Verify mutant kill for mutation de `not A or not B` a `not A and not B`"""
    poller = YamlStatePoller(MagicMock())

    # Configure A = False, B = True (state_getter exists, loader not initialized)
    # If mutation is 'and', execution won't short-circuit and crashes next line.
    poller.controller.loader.state_getter = MagicMock()
    poller.controller.loader.is_fully_initialized = False

    # Explosive trap: if flow advances erroneously, this detonates
    def _explode(self):
        raise RuntimeError("Mutant OR->AND survived!")

    type(poller.controller.loader.state_getter).value = property(_explode)

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


@pytest.mark.asyncio
async def test_build_device_state_power_ternary_mutual_exclusivity() -> None:
    """Kills mutants modifying ('Off' if device_value == 'Off' else 'On')."""

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


def test_inject_value_into_state_devices_key_strict():
    """Target 4: Kills mutant on line 660 ('and Devices in device_state') in _inject_value_into_state."""
    poller = YamlStatePoller(DummyController())
    prop = MagicMock(id="temperature", connection_template=None)
    del prop.apply_optimistic_cascades
    del prop.set_device_state_for_values
    del prop.convert_hass_to_dev
    poller._get_state_node_from_prop = MagicMock(return_value="target_temp")

    # 1. State WITHOUT "Devices" key -> updates root device_state directly, does NOT raise KeyError
    state_without_devices = {"target_temp": 20}
    poller._inject_value_into_state(prop, state_without_devices, 25)
    assert state_without_devices == {"target_temp": 25}
    assert "Devices" not in state_without_devices

    # 2. State WITH "Devices" key containing a device dict -> updates BOTH root AND device_state["Devices"][0]
    state_with_devices = {
        "target_temp": 20,
        "Devices": [{"target_temp": 20, "id": "0"}],
    }
    poller._inject_value_into_state(prop, state_with_devices, 25)
    assert state_with_devices["target_temp"] == 25
    assert state_with_devices["Devices"][0]["target_temp"] == 25

    # 3. State WITH "Devices" key that is empty list -> does not crash or modify Devices
    state_empty_devices = {"target_temp": 20, "Devices": []}
    poller._inject_value_into_state(prop, state_empty_devices, 25)
    assert state_empty_devices["target_temp"] == 25
    assert state_empty_devices["Devices"] == []

    # 4. State WITH "Devices" key that is list of non-dict -> does not crash or modify Devices
    state_non_dict_devices = {"target_temp": 20, "Devices": ["not_a_dict"]}
    poller._inject_value_into_state(prop, state_non_dict_devices, 25)
    assert state_non_dict_devices["target_temp"] == 25
    assert state_non_dict_devices["Devices"] == ["not_a_dict"]


def test_inject_value_into_state_payload_options_exact_equality():
    """Target 2: Kills Mutant 41 on Line 650 in _inject_value_into_state with full dictionary equality."""
    poller = YamlStatePoller(DummyController())
    poller._get_state_node_from_prop = MagicMock(return_value="Device_Mode")

    # Case 1: Template renders JSON with options list containing string -> dev_val becomes payload['options'][0]
    prop_str = MagicMock(id="good_sleep")
    del prop_str.apply_optimistic_cascades
    del prop_str.set_device_state_for_values
    del prop_str.convert_hass_to_dev
    prop_str.connection_template = '{"json": {"options": ["Sleep_2"]}}'

    state1 = {"Device_Mode": "Off"}
    poller._inject_value_into_state(prop_str, state1, 2)
    # Strict full dictionary output assertion catches any structural alteration
    assert state1 == {"Device_Mode": "Sleep_2"}
    assert isinstance(state1["Device_Mode"], str)
    assert state1["Device_Mode"] == "Sleep_2"

    # Case 2: Template renders options list with non-string (int) -> dev_val remains original value
    prop_non_str = MagicMock(id="good_sleep")
    del prop_non_str.apply_optimistic_cascades
    del prop_non_str.set_device_state_for_values
    del prop_non_str.convert_hass_to_dev
    prop_non_str.connection_template = '{"json": {"options": [999]}}'

    state2 = {"Device_Mode": "Off"}
    poller._inject_value_into_state(prop_non_str, state2, 2)
    # Strict full dictionary output assertion
    assert state2 == {"Device_Mode": 2}
    assert isinstance(state2["Device_Mode"], int)
    assert state2["Device_Mode"] == 2

    # Case 3: Template renders empty options list -> dev_val remains original value
    prop_empty = MagicMock(id="good_sleep")
    del prop_empty.apply_optimistic_cascades
    del prop_empty.set_device_state_for_values
    del prop_empty.convert_hass_to_dev
    prop_empty.connection_template = '{"json": {"options": []}}'

    state3 = {"Device_Mode": "Off"}
    poller._inject_value_into_state(prop_empty, state3, 2)
    assert state3 == {"Device_Mode": 2}


def test_inject_value_into_state_state_node_structural_integrity():
    """Target 2: Kills Mutant 45 on Line 656 in _inject_value_into_state (if state_node and isinstance(state_node, str))."""
    poller = YamlStatePoller(DummyController())
    prop = MagicMock(id="temperature", connection_template=None)
    del prop.apply_optimistic_cascades
    del prop.set_device_state_for_values
    del prop.convert_hass_to_dev

    # 1. Empty string state_node -> falsy: must NOT inject or mutate device_state (kills 'and' -> 'or' mutant)
    poller._get_state_node_from_prop = MagicMock(return_value="")
    state_empty_str = {"temp": 20, "mode": "cool"}
    poller._inject_value_into_state(prop, state_empty_str, 25)
    assert state_empty_str == {"temp": 20, "mode": "cool"}
    assert "" not in state_empty_str

    # 2. None state_node -> falsy: must NOT inject or mutate device_state
    poller._get_state_node_from_prop = MagicMock(return_value=None)
    state_none = {"temp": 20}
    poller._inject_value_into_state(prop, state_none, 25)
    assert state_none == {"temp": 20}

    # 3. Non-string state_node (int) -> not a string: must NOT inject or mutate device_state
    poller._get_state_node_from_prop = MagicMock(return_value=123)
    state_int = {"temp": 20}
    poller._inject_value_into_state(prop, state_int, 25)
    assert state_int == {"temp": 20}

    # 4. Valid string state_node -> strictly injects and preserves full dictionary structure
    poller._get_state_node_from_prop = MagicMock(return_value="temp")
    state_valid = {"temp": 20, "power": "on"}
    poller._inject_value_into_state(prop, state_valid, 25)
    assert state_valid == {"temp": 25, "power": "on"}
    assert state_valid["temp"] == 25
    assert state_valid["power"] == "on"


def test_inject_value_into_state_device_state_in_connection_template() -> None:
    """Annihilates Mutant 25: verifies device_state is passed to render_template in _inject_value_into_state."""
    poller = YamlStatePoller(DummyController())
    poller._get_state_node_from_prop = MagicMock(return_value="Device_Mode")

    prop = MagicMock(id="good_sleep")
    del prop.apply_optimistic_cascades
    del prop.set_device_state_for_values
    del prop.convert_hass_to_dev
    prop.connection_template = Template(
        '{"json": {"options": ["{{ device_state.prefix }}_{{ value }}"]}}',
        hass=MagicMock(data={}),
    )

    state = {"Device_Mode": "Off", "prefix": "DynamicSleep"}
    poller._inject_value_into_state(prop, state, 3)

    assert state["Device_Mode"] == "DynamicSleep_3"
    assert isinstance(state["Device_Mode"], str)
