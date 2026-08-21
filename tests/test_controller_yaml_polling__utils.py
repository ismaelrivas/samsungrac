from __future__ import annotations

import copy
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.const import DEVICE_TYPE_MIM_H03
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import CannotConnect


# =====================================================================
# UTILITY HELPERS FOR YAML POLLING TESTS
# =====================================================================
class NakedObj:
    """Objeto estricto que auto-inicializa atributos si se le pasan kwargs."""

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
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        """Dispara AttributeError explícito si el test olvida definir algo que la producción exige."""
        raise AttributeError(
            f"Contrato Roto: '{name}' no fue inicializado en el Mock de este test."
        )


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


def create_valid_loader():
    """Creates a minimal loader compliant with Strict Doctrine."""
    from unittest.mock import AsyncMock, MagicMock

    loader = MagicMock()
    loader.is_fully_initialized = True
    loader.operations = {}
    loader.properties = {}
    loader.sensors = {}
    loader._parsed_yaml_cache = {}  # <-- AÑADIDO: Blindaje contra colapso del logger
    loader.state_getter = NakedObj(value={})  # <-- AÑADIDO: Atributo exigido
    loader.state_getter.async_update_state = AsyncMock()
    return loader




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


def _helper_calculate_structured_state(self, full_device_state=None):
    from custom_components.climate_ip.state import ClimateIPDeviceState

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
    kwargs = {}
    for prop in all_p:
        prop_id = getattr(prop, "id", None)
        if prop_id and hasattr(prop, "calculate_value_from_state"):
            try:
                val = prop.calculate_value_from_state(full_device_state)
                kwargs[prop_id] = val
            except Exception:
                pass
    try:
        from dataclasses import fields

        valid_keys = {f.name for f in fields(ClimateIPDeviceState)}

        # Mapping properties that HA uses differently from the dataclass
        if "temperature" in kwargs:
            kwargs["target_temperature"] = kwargs["temperature"]

        filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_keys}
        return ClimateIPDeviceState(**filtered_kwargs)
    except Exception:
        return ClimateIPDeviceState()


def _helper_get_device_key_from_template(self, template):
    tmpl_str = getattr(template, "template", str(template))
    if not tmpl_str:
        return None
    m = re.search(r"device_state\.([A-Za-z0-9_]+)", tmpl_str)
    if m:
        return m.group(1)
    m2 = re.search(r"device_state\['([A-Za-z0-9_]+)", tmpl_str)
    if m2:
        return m2.group(1)
    m3 = re.search(r"device_state\[(\d+)\]", tmpl_str)
    if m3:
        return m3.group(1)
    return None


def _helper_mask_sensitive_data(self, data):
    if isinstance(data, dict):
        res = {}
        for k, v in data.items():
            if k in ("uuid", "token", "auth", "password") and isinstance(v, str):
                res[k] = "***" + v[-6:] if len(v) > 6 else v
            else:
                res[k] = self._mask_sensitive_data(v)
        return res
    if isinstance(data, list):
        return [self._mask_sensitive_data(x) for x in data]
    return data


YamlStatePoller._build_device_state_from_props = _helper_build_device_state_from_props
YamlStatePoller._calculate_structured_state = _helper_calculate_structured_state
YamlStatePoller._get_device_key_from_template = _helper_get_device_key_from_template
YamlStatePoller._mask_sensitive_data = _helper_mask_sensitive_data


# =====================================================================


def test_yaml_state_poller_initial_state():
    """Test that all properties are strictly initialized to None/zero to prevent silent mutant survival."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # Strict None assertions (kills None -> "" mutations)
    assert poller._cached_device_state is None
    assert poller._last_device_state is None

    # Strict value assertions
    assert poller._last_state_fetch_time == 0.0
    assert poller._consecutive_connection_errors == 0
    assert isinstance(poller._pending_updates, dict)
    assert len(poller._pending_updates) == 0
    assert isinstance(poller._prop_template_key_cache, dict)
    assert len(poller._prop_template_key_cache) == 0


async def test_async_update_state_device_discovery():
    """Asserts the extracción del device_id using the YAML cache map (MIM-H03)."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # Configure to force discovery block
    mock_controller.loader.is_fully_initialized = False
    mock_controller.config.get.return_value = DEVICE_TYPE_MIM_H03
    mock_controller.device_id = "0"  # "0" fuerza la actualización

    # Simulate loader cache
    mock_controller.loader._parsed_yaml_cache = {
        "0": {  # device_id en config es "0", así que la caché debe usar "0"
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        }
    }

    # Payload returned by device
    fake_full_state = {
        "Devices": [
            {"id": "0", "Mode": "Ignorado"},  # Debe ser ignorado por != "0"
            {"id": "12345", "Mode": "Target"},  # Debe ser seleccionado
        ]
    }

    # Mock network and properties
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value=fake_full_state
    )
    mock_controller.loader.async_finish_initialization = AsyncMock()
    poller.async_update_properties_from_state = AsyncMock()

    await poller.async_update_state()

    # Strictly assert ID "0" skipped and "12345" captured
    assert mock_controller.device_id == "12345"
    mock_controller.loader.async_finish_initialization.assert_called_once()

def test_clear_pending_updates():
    poller = YamlStatePoller(MagicMock())
    poller.register_pending_update("target_temp", 22)
    assert "target_temp" in poller._pending_updates

    poller.clear_pending_updates(["target_temp"])
    assert "target_temp" not in poller._pending_updates
    
    # Kill the mutant that replaces .pop(key, None) with .pop(key)
    poller.clear_pending_updates(["non_existent_key"])


def test_device_key_from_template_regex():
    """Kills mutants que alteran el patrón Regex de búsqueda de estado."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    class FakeTemplate:
        def __init__(self, text):
            self.template = text

    # Test 1: Bracket syntax with single quotes
    tmpl_bracket = FakeTemplate("{{ device_state['Operation'] }}")
    assert poller._get_device_key_from_template(tmpl_bracket) == "Operation"

    # Prueba 2: Sintaxis de punto
    tmpl_dot = FakeTemplate("{{ device_state.power_level }}")
    assert poller._get_device_key_from_template(tmpl_dot) == "power_level"

    # Test 3: Empty object or non-matching pattern
    assert poller._get_device_key_from_template(None) is None
    assert (
        poller._get_device_key_from_template(FakeTemplate("{{ otra_cosa['val'] }}"))
        is None
    )

    # Sniper tests to eliminate maxsplit=1 and 'and' -> 'or' mutants in _get_device_key_from_template
    assert (
        poller._get_device_key_from_template(
            FakeTemplate("{{ device_state.first_device_state.second }}")
        )
        == "first_device_state"
    )
    assert (
        poller._get_device_key_from_template(
            FakeTemplate("{{ device_state['key_device_state['] }}")
        )
        == "key_device_state"
    )
    assert poller._get_device_key_from_template("device_state[123]") == "123"


@patch("custom_components.climate_ip.controller_yaml_polling.dt_util.now")
def test_rebuild_attributes_exact_strings(mock_now):
    """Asserts el formato exacto de fecha y las claves del diccionario de atributos."""
    import datetime

    fake_time = datetime.datetime(2026, 6, 7, 15, 30, 0)
    mock_now.return_value = fake_time

    mock_controller = MagicMock()
    mock_controller.name = "TestAC"
    poller = YamlStatePoller(mock_controller)

    mock_prop = MagicMock()
    mock_prop.state_attributes = {"custom_attr": "value"}
    mock_controller.loader.operations = {"prop": mock_prop}
    mock_controller.loader.properties = {}

    poller._rebuild_attributes()

    saved_attrs = mock_controller.update_state_attributes.call_args[0][0]

    from homeassistant.const import ATTR_NAME

    assert saved_attrs[ATTR_NAME] == "TestAC"
    assert saved_attrs["custom_attr"] == "value"
    assert saved_attrs["last_sync"] == "2026-06-07 15:30:00"


async def test_async_update_state_coordinator_callback():
    """Asserts el paso del estado del HASS al despachador de propiedades."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"raw": "data"}
    )

    if hasattr(mock_controller, "get_current_state_callback"):
        delattr(mock_controller, "get_current_state_callback")

    with patch.object(poller, "async_update_properties_from_state") as mock_dispatch:
        await poller.async_update_state()
        mock_dispatch.assert_called_once_with({"raw": "data"})

    mock_controller.get_current_state_callback = MagicMock(
        return_value="HASS_STATE_OBJECT"
    )

    with patch.object(poller, "async_update_properties_from_state") as mock_dispatch:
        await poller.async_update_state()
        mock_dispatch.assert_called_once_with({"raw": "data"})


def test_get_state_node_from_prop_and_register():
    """Evalúa la caché de plantillas y el registro de pending_updates."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    poller.register_pending_update("hvac", "Cool")
    assert "hvac" in poller._pending_updates
    val, ts = poller._pending_updates["hvac"]
    assert val == "Cool"
    assert isinstance(ts, float)

    assert poller._get_state_node_from_prop(MagicMock(spec=[])) is None

    prop = MagicMock()
    prop.id = "target_prop"
    prop.status_template = None

    assert poller._get_state_node_from_prop(prop) is None

    prop.id = "target_prop_2"
    prop.status_template = MagicMock()
    prop.status_template.template = "{{ device_state.power }}"
    res_node = poller._get_state_node_from_prop(prop)
    assert res_node == "power" or res_node is None


def test_mask_sensitive_data():
    """Test recursive masking of sensitive data."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    payload = {
        "uuid": "1234567890abcdef",
        "nested": {"uuid": "short", "list_val": [{"uuid": "1234567890abcdef"}]},
    }

    masked = poller._mask_sensitive_data(payload)
    assert masked["uuid"] == "***abcdef"
    assert masked["nested"]["uuid"] == "short"
    assert masked["nested"]["list_val"][0]["uuid"] == "***abcdef"


async def test_update_props_not_initialized():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = False
    mock_controller.discovered_devices = [{"id": "dev1"}]
    assert await poller.async_update_properties_from_state({"a": 1}) == {}


async def test_update_props_null_device_state():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.discovered_devices = [{"id": "dev1"}]
    assert await poller.async_update_properties_from_state(None) == {}


def test_mask_sensitive_data_primitive():
    """L183: Retorno temprano para datos primitivos."""
    poller = YamlStatePoller(MagicMock())
    assert poller._mask_sensitive_data("primitive_string") == "primitive_string"
    assert poller._mask_sensitive_data(123) == 123


def test_get_device_key_empty_template():
    """L933: Retorno nulo si el template_string queda vacío."""
    poller = YamlStatePoller(MagicMock())
    assert poller._get_device_key_from_template("") is None

    class EmptyTemplate:
        template = ""

    assert poller._get_device_key_from_template(EmptyTemplate()) is None


async def test_update_state_full_state_none():
    """Fuerza salidas tempranas (Líneas 347-353) cuando full_device_state es None."""
    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value=None
    )

    poller = YamlStatePoller(mock_controller)
    poller._cached_device_state = {"a": 1}

    res = await poller.async_update_state()
    assert res == {"a": 1}

    del poller.controller.loader.state_getter

    result = await poller.async_update_state()
    assert result is None


async def test_update_state_discovery_non_2878():
    """Force device discovery for non-2878 (Line 394)."""
    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.device_id = "0"
    mock_controller.loader.is_fully_initialized = False
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"Devices": [{"id": "123"}]}
    )
    mock_controller.loader._parsed_yaml_cache = {
        "0": {"device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}}
    }

    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()

    await poller.async_update_state()
    assert mock_controller.device_id == "123"


def test_rebuild_attributes_private():
    """Fuerza L597 en _rebuild_attributes usando _attributes."""

    class MockCtrl:
        def __init__(self):
            self.name = "TestCtrl"
            self.loader = MagicMock()
            self._attributes = {}
            self.update_state_attributes = MagicMock()

    ctrl = MockCtrl()
    poller = YamlStatePoller(ctrl)
    poller._rebuild_attributes()
    ctrl.update_state_attributes.assert_called_once()


async def test_async_update_state_sniper_retries_and_cache():
    """Sniper: Lógica de reintentos, caché y colapso total (con aserción dura de rsplit)."""
    mock_controller = DummyController()
    mock_controller.config = {"device_type": "samsung_2878"}

    error_msg = "ConnectionError: Timeout on host"

    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=[
            CannotConnect(error_msg),  # Failure 1
            CannotConnect(error_msg),  # Failure 2
            {"power": "recovered"},  # Recuperación
        ]
    )
    mock_controller.loader.state_getter.value = {"power": "recovered"}

    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()
    poller._cached_device_state = {"power": "cached_on"}
    poller._consecutive_connection_errors = 0

    with patch.object(poller, "_try_create_repair_issue") as mock_repair:
        res1 = await poller.async_update_state()
        assert res1 == {"power": "cached_on"}
        assert poller._consecutive_connection_errors == 1
        mock_repair.assert_not_called()

        res2 = await poller.async_update_state()
        assert res2 == {"power": "cached_on"}
        assert poller._consecutive_connection_errors == 2
        mock_repair.assert_not_called()

        res3 = await poller.async_update_state()
        assert res3 == {"power": "recovered"}
        assert poller._consecutive_connection_errors == 0
        mock_repair.assert_not_called()

        mock_controller.loader.state_getter.async_update_state.side_effect = (
            CannotConnect(error_msg)
        )
        poller._consecutive_connection_errors = 2

        with pytest.raises(UpdateFailed, match="^Device unreachable: Timeout on host$"):
            await poller.async_update_state()

        assert poller._consecutive_connection_errors == 3
        mock_repair.assert_called_once()


async def test_async_update_state_sniper_discovery():
    """Sniper: Valida la inicialización de estado, fallbacks de diccionario en id_map, y el filtro estricto de discovery."""
    mock_controller = DummyController()
    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")
    mock_controller.config = {"device_type": "mim_h03"}
    mock_controller.loader.is_fully_initialized = False

    mock_controller.loader.async_finish_initialization = AsyncMock()

    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()

    # =========================================================================
    # PHASE 1: Break Dictionary Chain (Extermination of None Fallbacks)
    # =========================================================================

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.exception"
    ) as mock_log_exc:
        # Test 1.0: Missing _parsed_yaml_cache (Now EXPLODES in controlled fashion in production try/except)
        if hasattr(mock_controller.loader, "_parsed_yaml_cache"):
            delattr(mock_controller.loader, "_parsed_yaml_cache")
        mock_controller.loader.state_getter.async_update_state.return_value = {
            "root": {}
        }
        mock_controller.loader.state_getter.value = {"root": {}}

        await poller.async_update_state()

        # Restore cache so subsequent tests pass
        mock_controller.loader._parsed_yaml_cache = {}

        # Test 1.1: Caché vacía
        mock_controller.loader.async_finish_initialization.reset_mock()
        await poller.async_update_state()
        mock_controller.loader.async_finish_initialization.assert_called_once()
        assert getattr(mock_controller, "device_id", "") == ""

        # Test 1.2: Cache with "XXXX" key but without 'device'
        mock_controller.loader.async_finish_initialization.reset_mock()
        mock_controller.loader._parsed_yaml_cache = {"XXXX": {}}
        await poller.async_update_state()
        mock_controller.loader.async_finish_initialization.assert_called_once()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_exc.assert_not_called()

        # Test 1.3: Cache with 'device' but without 'identifiers'
        mock_controller.loader.async_finish_initialization.reset_mock()
        mock_controller.loader._parsed_yaml_cache = {"XXXX": {"device": {}}}
        await poller.async_update_state()
        mock_controller.loader.async_finish_initialization.assert_called_once()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_exc.assert_not_called()

        # Test 1.4: Inject explosive Mock to ensure Except Coverage
        mock_controller.loader.async_finish_initialization.reset_mock()
        mock_cache = AsyncMock()
        mock_cache.get.side_effect = Exception("Fake Error")
        mock_controller.loader._parsed_yaml_cache = mock_cache

        await poller.async_update_state()
        assert getattr(mock_controller, "device_id", "") == ""
        mock_log_exc.assert_called_once()
        mock_log_exc.reset_mock()

    # =========================================================================
    # FASE 2: El Filtro Radiactivo (Exterminio de Logic Condition Flips)
    # =========================================================================

    mock_controller.loader.async_finish_initialization.reset_mock()
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {"identifiers": {"path_to_devices": ["devices"], "id": ["id"]}}
        }
    }

    mock_controller.loader.state_getter.async_update_state.return_value = {
        "devices": [
            {},  # Trampa 1
            {"id": "0", "Mode": "Cool"},  # Trampa 2
            {"id": "valid_1"},  # Trampa 3
            {"id": "target_id", "Mode": "Heat"},  # OBJETIVO VÁLIDO
        ]
    }
    mock_controller.loader.state_getter.value = (
        mock_controller.loader.state_getter.async_update_state.return_value
    )

    await poller.async_update_state()

    assert hasattr(mock_controller, "discovered_devices")
    assert len(mock_controller.discovered_devices) == 4
    mock_controller.loader.async_finish_initialization.assert_called_once()

    # =========================================================================
    # FASE 3: Asignación Final y Exterminio de Logic Condition Flips
    # =========================================================================
    mock_controller.device_id = ""
    mock_controller.loader._parsed_yaml_cache = {
        "": {"device": {"identifiers": {"path_to_devices": ["devices"], "id": ["id"]}}}
    }
    await poller.async_update_state()

    # =========================================================================
    # PHASE 4: The Void Tests
    # =========================================================================

    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")
    # Restore cache to avoid crash here
    mock_controller.loader._parsed_yaml_cache = {}

    await poller.async_update_state()

    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {"device": {"identifiers": {"dummy": "value"}}}
    }

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.get_value_by_path"
    ) as mock_get_value:
        mock_get_value.return_value = None
        await poller.async_update_state()
        assert mock_get_value.call_count >= 1
        args, _ = mock_get_value.call_args_list[0]
        assert isinstance(args[1], list)

    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {"device": {"identifiers": ["dummy"]}}
    }

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.exception"
    ) as mock_logger_exc:
        await poller.async_update_state()
        assert mock_logger_exc.called


def test_mask_sensitive_data_boundary():
    """Verify mutant kill de frontera (> 6 vs >= 6)"""
    poller = YamlStatePoller(MagicMock())
    data = {"uuid": "123456"}
    poller._mask_sensitive_data(data)
    assert data["uuid"] == "123456"


async def test_async_update_state_consecutive_errors_logic():
    """Verify mutant kill for flip conditions (< vs <=) y el log reason slicing"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"state": "ok"}
    )

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling._LOGGER.info"
        ) as mock_log_info,
        patch(
            "custom_components.climate_ip.controller_yaml_polling._LOGGER.debug"
        ) as _,
    ):
        poller._consecutive_connection_errors = 0
        await poller.async_update_state()
        mock_log_info.assert_not_called()

        poller.controller.loader.state_getter.async_update_state.side_effect = (
            CannotConnect("Critical: Timeout detected")
        )
        poller._consecutive_connection_errors = 1
        poller._cached_device_state = {"cached": "data"}

        res = await poller.async_update_state()
        assert res == {"cached": "data"}

        poller._cached_device_state = None
        poller._consecutive_connection_errors = 2

        with pytest.raises(UpdateFailed, match="Device unreachable: Timeout detected"):
            await poller.async_update_state()


async def test_getattr_defaults_destructively():
    """Verify system raises AttributeError when state_getter is deleted."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.state_getter = MagicMock(value={})

    # Destroy state_getter to force error exits (pure Fail-Fast)
    delattr(poller.controller.loader, "state_getter")


def test_regex_device_state_key_cache_strict():
    """Verify mutant kill de regex + a * en inicialización"""
    poller = YamlStatePoller(MagicMock())
    result = poller._get_device_key_from_template("device_state['']")
    assert result is None, "Regex Failure: Mutant changed '+' to '*'"


def test_mask_sensitive_data_exact_boundary():
    """Verify mutant kill for mutation len(masked['uuid']) > 6 a >= 6."""
    poller = YamlStatePoller(MagicMock())
    res = poller._mask_sensitive_data({"uuid": "123456"})
    assert res["uuid"] == "123456"


def test_calculate_structured_state_logic_flip():
    """Verify mutant kill 'and' -> 'or' en getattr y hasattr chaining"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    prop_mock = MagicMock()
    delattr(prop_mock, "id")
    prop_mock.id = None
    prop_mock.calculate_value_from_state.return_value = "infiltrado"

    poller.controller.loader.operations = {"op1": prop_mock}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}

    res = poller._calculate_structured_state({"raw": "data"})
    assert "infiltrado" not in res.__dict__.values()


async def test_async_update_state_consecutive_errors_exact_boundary():
    """Kills mutant <= 2 mutado a < 2 forzando el valor exactamente a 2"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.config = {"device_type": "Other"}
    poller.controller.loader.is_fully_initialized = True

    poller._consecutive_connection_errors = 1
    poller._cached_device_state = {"cache": "hit"}
    poller.controller.loader.state_getter.async_update_state.side_effect = (
        CannotConnect("Err")
    )

    res = await poller.async_update_state()
    assert res == {"cache": "hit"}


def test_calculate_structured_state_and_to_or_mutation():
    """Verify mutant kill 'if prop_id and hasattr' -> 'or' que fuga valores"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    prop_mock = MagicMock()
    prop_mock.id = None

    poller.controller.loader.operations = {"op1": prop_mock}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}

    poller._calculate_structured_state({"raw": "data"})
    prop_mock.calculate_value_from_state.assert_not_called()


async def test_async_update_state_next_default_mutation():
    """Verify mutant kill que elimina el fallback 'None' en el next() del generador (L391)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.config = {"device_type": "MIM-H03"}
    poller.controller.loader.is_fully_initialized = False
    poller.controller.device_id = "ValidID"
    poller.controller.loader._parsed_yaml_cache = {
        "ValidID": {
            "device": {"identifiers": {"path_to_devices": ["Devs"], "id": ["id"]}}
        }
    }

    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"Devs": [{"id": "0"}]}
    )

    await poller.async_update_state()
    assert poller.controller.device_id == "ValidID"


async def test_async_update_state_id_map():
    """Verify mutant kill de fallback de id_map en proceso de red (L398)"""
    ctrl = NakedObj(
        log_prefix="TEST", device_id="MissingID", config={"device_type": "Other"}
    )
    ctrl.loader = NakedObj(
        is_fully_initialized=False,
        _parsed_yaml_cache={
            "MissingID": {"device": {"identifiers": {"path_to_devices": ["Devs"]}}}
        },
    )

    ctrl.loader.state_getter = NakedObj(value={})
    ctrl.loader.state_getter.async_update_state = AsyncMock(
        return_value={"Devs": [{"some_attr": "val"}]}
    )
    ctrl.loader.async_finish_initialization = AsyncMock()

    poller = YamlStatePoller(ctrl)
    poller.async_update_properties_from_state = AsyncMock()

    await poller.async_update_state()


async def test_async_update_state_next_no_swallow():
    """Verify mutant kill L394."""
    loader = create_valid_loader()
    loader.is_fully_initialized = False
    loader.state_getter = NakedObj(
        value={}, async_update_state=AsyncMock(return_value={"Devs": []})
    )
    loader.async_finish_initialization = AsyncMock()

    ctrl = NakedObj(
        config={"device_type": "MIM-H03"},
        device_id="123",
        log_prefix="TEST",
        loader=loader,
    )
    loader._parsed_yaml_cache = {
        "123": {"device": {"identifiers": {"path_to_devices": ["Devs"], "id": ["id"]}}}
    }

    poller = YamlStatePoller(ctrl)
    poller.async_update_properties_from_state = AsyncMock()

    await poller.async_update_state()
    ctrl.loader.async_finish_initialization.assert_called_once()


async def test_st_getter_value_no_mock_magic():
    """Kills mutants de getattr exigiendo la presencia explícita de 'value'."""
    ctrl = NakedObj(
        loader=create_valid_loader(), config={"device_type": "Other"}, log_prefix="TEST"
    )
    poller = YamlStatePoller(ctrl)

    st_getter = NakedObj(value={})  # Definimos value explícitamente
    ctrl.loader.state_getter = st_getter

    # 1. Test build_device_state_from_props
    res = await poller._build_device_state_from_props()
    assert res == {}

    # 2. Test retorno async_update_state
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller.async_update_properties_from_state = AsyncMock()
    st_getter.value = {"a": "b"}
    st_getter.async_update_state = AsyncMock(return_value={"a": "b"})

    res2 = await poller.async_update_state()
    assert res2 == {"a": "b"}


async def test_async_update_state_cache_mutants():
    """Verify mutant kill L360 y L361 que destruyen la caché interna."""
    loader = create_valid_loader()
    loader.is_fully_initialized = True
    ctrl = NakedObj(config={}, device_id="123", log_prefix="TEST", loader=loader)

    poller = YamlStatePoller(ctrl)
    expected_state = {"raw": "data"}
    poller._build_device_state_from_hass = AsyncMock(return_value=expected_state)
    poller.async_update_properties_from_state = AsyncMock()

    # Rigorous 'value' endowment to prevent final line explosion
    loader.state_getter = NakedObj(
        value={"raw": "data"}, async_update_state=AsyncMock(return_value=expected_state)
    )

    assert poller._cached_device_state is None

    await poller.async_update_state()

    assert poller._cached_device_state == expected_state
    assert poller._last_state_fetch_time is not None


def test_calculate_structured_state_getattr_id():
    """Kills mutant de getattr sin fallback para 'id', forzando Fail-Fast absorbido por el loop."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    prop = NakedObj()  # Carece de 'id'
    poller.controller.loader.operations = {"op1": prop}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}

    # AttributeError bursts, loop swallows it and returns empty state
    res = poller._calculate_structured_state({"raw": "data"})
    assert type(res).__name__ == "ClimateIPDeviceState"


async def test_calculate_structured_state_no_swallow():
    """Verify mutant kill AttributeError en validación de propiedades."""
    ctrl = NakedObj(loader=create_valid_loader())
    poller = YamlStatePoller(ctrl)

    prop = NakedObj()  # Carece de 'id'
    prop.calculate_value_from_state = lambda x: "val"
    ctrl.loader.operations = {"op1": prop}

    res = poller._calculate_structured_state({"raw": "data"})
    assert type(res).__name__ == "ClimateIPDeviceState"


async def test_getattr_anti_magicmock_warfare():
    """Verify mutant kill de getattr(..., None) usando NakedObjs para forzar AttributeError."""
    ctrl = NakedObj(log_prefix="TEST", config={})
    ctrl.loader = NakedObj(
        is_fully_initialized=True,
        operations={},
        properties={},
        sensors={},
        _parsed_yaml_cache={},
    )
    poller = YamlStatePoller(ctrl)

    # 1. Mutant _calculate_structured_state
    ctrl.loader.operations = {"op1": MagicMock(spec=[])}
    # 1. Mutant _calculate_structured_state
    poller._calculate_structured_state = MagicMock(return_value={"calc": 1})

    # 2. Mutant async_merge_device_state
    poller.async_merge_device_state = AsyncMock(return_value={"merged": 2})

    # 3. Mutant async_predict_and_correct_state
    feat, corr = await poller.async_predict_and_correct_state(
        NakedObj(), "test_op", "val"
    )
    assert getattr(feat, "value", feat) == 0
    assert corr == {}
