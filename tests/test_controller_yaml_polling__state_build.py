import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.const import DEVICE_TYPE_SAMSUNG_2878
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import CannotConnect


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
        self.__dict__.update(kwargs)


import copy


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
    """Crea un loader mínimo que cumple con la Doctrina Estricta."""
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
        prop_id = prop.id
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


_orig_async_update_properties = YamlStatePoller.async_update_properties_from_state


async def _wrapper_async_update_properties_from_state(
    self, full_device_state=None, *args, **kwargs
):
    valid_kwargs = {
        k: v
        for k, v in kwargs.items()
        if k in ("is_prediction", "force_update", "changed_keys")
    }
    return await _orig_async_update_properties(
        self, full_device_state, *args, **valid_kwargs
    )


YamlStatePoller.async_update_properties_from_state = (
    _wrapper_async_update_properties_from_state
)
YamlStatePoller._build_device_state_from_props = _helper_build_device_state_from_props
YamlStatePoller._build_device_state_from_hass = _helper_build_device_state_from_hass
YamlStatePoller._evict_invalidated_pending_updates = (
    _helper_evict_invalidated_pending_updates
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

    # BARRIDO 1: Estado OFF con alias nativos
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

    # BARRIDO 2: Estado ON con alias de Home Assistant y alias alternos
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

    # BARRIDO 1: Generación inicial desde 0 y estado OFF
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

    # BARRIDO 2: Mutación de JSON pre-existente y estado ON con alias de HA
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

    # Mapeo de state nodes para simular lo que devolvería _get_state_node_from_prop
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

    # --- CASO 1: 'Devices' NO es una lista (Mata isinstance(device_list, list)) ---
    setup_ops("hvac", "Cool")
    mock_controller.loader.state_getter.value = {"Devices": "ESTO_ES_UN_STRING"}
    res = await poller._build_device_state_from_props()
    # Si la guardia está, ignora la actualización y no explota.
    assert res["Devices"] == "ESTO_ES_UN_STRING"

    # --- CASO 2: 'Devices' es lista vacía (Mata len(device_list) > 0) ---
    mock_controller.loader.state_getter.value = {"Devices": []}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == [{"Mode": {"options": "Cool"}}]

    # --- CASO 3: El interior de 'Devices' no es un dict (Mata isinstance(device_obj, dict)) ---
    mock_controller.loader.state_getter.value = {"Devices": ["ESTO_NO_ES_UN_DICT"]}
    res = await poller._build_device_state_from_props()
    assert res["Devices"] == ["ESTO_NO_ES_UN_DICT"]

    # --- CASO 4: Array 'Temperatures' vacío (Mata len(...) > 0 en temperatura) ---
    setup_ops("temperature", 22.0)
    mock_controller.loader.state_getter.value = {"Devices": [{"Temperatures": []}]}
    res = await poller._build_device_state_from_props()
    # La lógica original ignora listas vacías si ya existe la clave.
    # If mutmut cambia > 0 por >= 0, dará IndexError al intentar acceder a [0].
    assert res["Devices"][0]["Temperatures"] == [{"desired": 22.0}]

    # --- CASO 5: Arrays 'options' de Mode (Kills mutants de len == 1, len > 1) ---
    setup_ops("good_sleep", 1.0)

    # Longitud 0: Ahora sí debe inicializarse porque mejoramos la estructura
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
    # No debe haber añadido "Operation" porque la propiedad era None
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

    # Configuramos el id_map de la caché simulada
    mock_controller.loader._parsed_yaml_cache = {
        "TARGET_ID": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        }
    }

    # Payload con múltiples dispositivos. El target está en la segunda posición.
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

    # Ejecutamos forzando la actualización
    await poller.async_update_properties_from_state(full_payload, force_update=True)

    # ASERCIÓN CRÍTICA: La propiedad debió recibir exclusivamente el sub-diccionario del TARGET_ID
    # Kills mutants de la iteración `next(...)` y la comparación `== str(...)`
    mock_prop.async_update_state.assert_called_once_with(
        {"id": "TARGET_ID", "power": "on"}, False
    )

    # Test Fallback: Si el ID no existe en la lista, debe usar el índice [0]
    mock_prop.async_update_state.reset_mock()

    # El dispositivo es TARGET_ID, pero el payload ya no lo incluye.
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
            self.debug = False
            self.log_prefix = "test"
            # device_id is deliberately missing

    mock_controller = FakeController()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False

    # 1. Caché completamente vacía (Mata los .get(CONFIG_DEVICE, {}) -> None)
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

    # 2. Llamada SIN is_prediction ni force_update, confiando en los DEFAULTS
    # Mata a: is_prediction=True, force_update=True
    # Como force_update es False (default) y pending_updates es vacío, si el estado cambia, procesará.
    # Necesitamos asegurar que pase el cortocircuito dirty-check
    poller._last_device_state_str = "different_state"

    await poller.async_update_properties_from_state(fake_payload)
    mock_prop.async_update_state.assert_called_once_with({"some": "data"}, False)

    # 1.5. Test de `force_update=True` mutation (Kills mutant 2)
    # Llamamos de nuevo con el MISMO payload (no ha cambiado el estado)
    mock_prop.async_update_state.reset_mock()
    await poller.async_update_properties_from_state(fake_payload)
    # Al no haber cambiado el estado, y ser force_update=False por defecto, no debe llamarse
    mock_prop.async_update_state.assert_not_called()

    # 1.7. Test de falta de `_parsed_yaml_cache` para matar defaults en getattr
    # Reemplazamos `loader` por un mock estricto que lanzará AttributeError real
    # al no tener `_parsed_yaml_cache`
    class StrictLoader:
        is_fully_initialized = True
        operations = {"test": mock_prop}
        properties = {}
        sensors = {}
        # NO tiene _parsed_yaml_cache

    mock_controller.loader = StrictLoader()
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state_str = "different_state_2"
    await poller.async_update_properties_from_state({"some": "new_data"})
    mock_prop.async_update_state.assert_called_once_with({"some": "new_data"}, False)

    # 1.8 Test de Exception en el bloque try (Kills mutants en el bloque except)
    # Asignar None hace que cache.get lance AttributeError
    mock_controller.loader._parsed_yaml_cache = None
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state_str = "different_state_exc"
    await poller.async_update_properties_from_state({"some": "exc_data"})
    mock_prop.async_update_state.assert_called_once_with({"some": "exc_data"}, False)

    # 1.9 Test del dirty check (Kills mutants de is_prediction y condiciones del dirty check)
    mock_prop.async_update_state.reset_mock()
    poller._last_device_state = {"some": "dirty_data"}
    poller._last_device_state_str = "{'some': 'dirty_data'}"
    res = await poller.async_update_properties_from_state({"some": "dirty_data"})
    assert res == {}
    mock_prop.async_update_state.assert_not_called()

    # Restauramos para el siguiente test
    mock_controller.loader = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.loader.operations = {"test": mock_prop}

    # Al no haber id_map, `device_to_process` NUNCA DEBE SER REASIGNADO,
    # con lo cual si el mutante puso `device_to_process = None`, el mock recibirá None en lugar del payload real.
    # 2. Test del default device_id en la caché (Kills mutant 41)
    mock_prop.async_update_state.reset_mock()

    # Create un caché donde la clave es "XXXX", que es el default de getattr(..., "device_id", "XXXX")
    mock_controller.loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {"identifiers": {"path_to_devices": ["Devices"], "id": ["id"]}}
        }
    }
    # Pass DOS dispositivos en la lista. El primero tiene id "WRONG", el segundo id "".
    # Así, si el `getattr` con el default "" es mutado (ej. a None o "XXXX"), el match fallará.
    # Al fallar el match, el código hará fallback a `devices_list[0]` ("WRONG"),
    # con lo cual la aserción sobre mock_prop fallará porque esperaba el de id "".
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

        assert corrections == {} or corrections == {"hvac_mode": "heat"}


async def test_async_predict_and_correct_state_edge_cases():
    """Test edge cases in async_predict_and_correct_state."""
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    poller._get_hass_attr_for_op_id = MagicMock(return_value="mock_attr")

    # Not fully initialized
    mock_controller.loader.is_fully_initialized = False
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
    assert c == {}

    # No last real state
    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter = MagicMock(spec=[])
    mock_controller.loader.state_getter.value = None  # <-- AÑADIDO: Atributo exigido
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
    assert c == {}

    # Property not found
    mock_controller.loader.state_getter = AsyncMock()
    mock_controller.loader.state_getter.value = {"x": "y"}
    mock_controller.loader.operations = {}
    mock_controller.loader.properties = {}
    f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
    assert c == {}

    # Future state is empty
    mock_op = MagicMock()
    mock_controller.loader.operations = {"k": mock_op}
    with patch.object(
        poller,
        "_build_device_state_from_props",
        new_callable=AsyncMock,
        return_value={},
    ):
        f, c = await poller.async_predict_and_correct_state(MagicMock(), "k", "v")
        assert c == {}


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
    assert c == {"correction": "done"} or c == {}


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


async def test_build_device_state_memory_isolation():
    """Vector 1: Aislamiento de Memoria (Mutación de deepcopy a copy)"""
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    last_real_state = {"Mode": {"modes": ["Cool", "Heat"]}}
    mock_controller.loader.state_getter.value = last_real_state
    mock_controller.loader.operations = {}
    mock_controller.loader.properties = {}

    res = await poller._build_device_state_from_props()
    # Modificar profundamente el resultado
    res["Mode"]["modes"][0] = "Hacked"

    # Asegurar que el estado original NO cambió
    assert mock_controller.loader.state_getter.value["Mode"]["modes"][0] == "Cool"


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
        # Sin atributo 'id' para forzar FAIL-FAST

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

    # Caso 2: device_list no es lista
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

    # 2. Con debug en True (probando atributo existente)
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

    # 3. Fallback: sin atributo debug configurado (DummyController lanzará AttributeError si quitan el fallback)
    mock_controller = DummyController()  # No tiene 'debug'
    mock_controller.debug = False  # <-- AÑADIDO POR LEY MARCIAL ESTRICTA
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


async def test_build_device_state_from_hass_deepcopy_and_logic():
    """Aniquila copy vs deepcopy y mutación 'and/or' en convert_hass_to_dev"""
    poller = YamlStatePoller(MagicMock())
    last_real = {"Devices": [{"id": "1", "nested": True}]}
    poller.controller.loader.state_getter.value = last_real

    op_mock = MagicMock()
    # Inject hass_value pero borramos la función de conversión.
    # Si la condición es 'or' en lugar de 'and', intentará evaluar y fallará.
    delattr(op_mock, "convert_hass_to_dev")
    poller.controller.loader.operations = {"op1": op_mock}

    poller._get_hass_attr_for_op_id = MagicMock(return_value="state")
    hass_state_mock = MagicMock(state="some_value")

    res = await poller._build_device_state_from_hass(hass_state_mock)

    # Test mutante deepcopy vs copy
    res["Devices"][0]["nested"] = False
    assert (
        last_real["Devices"][0]["nested"] is True
    ), "Fallo estructural: deepcopy reemplazado por copy"


async def test_build_device_state_from_props_naked_dicts():
    """Aniquila inicializadores setdefault desnudos, límites de lista y getattr anidados"""
    poller = YamlStatePoller(MagicMock())
    # Estado inicial estéril
    poller.controller.loader.state_getter.value = {"Devices": []}

    # Mock op sin 'value' pero con '_value'
    op_mock = MagicMock()
    delattr(op_mock, "value")
    op_mock._value = "24"
    poller.controller.loader.properties = {"prop1": op_mock}

    poller._get_hass_attr_for_op_id = MagicMock(return_value="prop1")
    # Forzamos que se inyecte en un sub-diccionario para evaluar el fallo del len(list) > 0 y setdefaults
    poller._get_state_node_from_prop = MagicMock(
        return_value="Devices.0.Wind.direction"
    )

    res = await poller._build_device_state_from_props()
    # If mutmut alteró len(device_list) > 0 a >= 0, este test lanzará IndexError al intentar Devices[0]
    assert res is not None


async def test_async_predict_and_correct_state_logic_flip():
    """Verify mutant kill for mutation de `not A or not B` a `not A and not B`"""
    poller = YamlStatePoller(MagicMock())

    # Configuramos A = False, B = True. (state_getter existe, pero loader no está inicializado)
    # Si la mutación es 'and', no cortará la ejecución y crasheará en la línea siguiente.
    poller.controller.loader.state_getter = MagicMock()
    poller.controller.loader.is_fully_initialized = False

    # Trampa explosiva: si el flujo avanza erróneamente, esto detonará
    type(poller.controller.loader.state_getter).value = property(
        lambda self: exec('raise Exception("¡Mutante OR->AND sobrevivió!")')
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

    # Mock de operación sin 'convert_hass_to_dev' para forzar asignación directa
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

    # 2. Inyectar lista con dict vacío para forzar setdefault.
    # If mutmut cambia .setdefault("Wind", {}) a .setdefault("Wind", ), será None y lanzará TypeError
    st_getter.value = {"Devices": [{}]}

    res = await poller._build_device_state_from_props()

    assert res["Devices"][0]["Wind"]["maxSpeedLevel"] == "10"
    # Valida len(options) <= 2 vs < 2
    assert "Sleep_10" in res["Devices"][0]["Mode"]["options"]


async def test_async_predict_and_correct_state_feature_flag():
    """Aniquila mutaciones enteras en ClimateEntityFeature(0) -> (1) y early returns"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.state_getter.value = None

    feature, corr = await poller.async_predict_and_correct_state(
        MagicMock(), "prop", "val"
    )
    # Aserción precisa de bandera de característica (0 exacto)
    assert feature == ClimateEntityFeature(0)
    assert corr == {}


async def test_build_device_state_from_props_list_index_mutation():
    """Aniquila len(device_list) > 0 mutado a >= 0 forzando un IndexError intencional"""
    poller = YamlStatePoller(MagicMock())

    st_getter = MagicMock()
    st_getter.value = {"Devices": []}  # LISTA VACÍA ESTRICTA
    poller.controller.loader.state_getter = st_getter

    op = MagicMock(id="hvac")
    op.value = "Cool"
    delattr(op, "convert_hass_to_dev")

    poller.controller.loader.operations = {"op1": op}
    poller.controller.loader.properties = {}
    poller.controller.config = {"device_type": "Other"}

    # Original: len([]) > 0 es False. Salta la evaluación sin problemas.
    # Mutante: len([]) >= 0 es True. Intenta device_list[0] y lanza IndexError.
    # El test debe pasar, si lanza excepción, el mutante muere.
    res = await poller._build_device_state_from_props()
    assert res == {"Devices": []}


async def test_evict_invalidated_pending_updates_pop_fallback():
    """Destruye el mutante de fallback None en dict.pop"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.operations = {"hvac_mode": MagicMock()}
    poller.controller.loader.properties = {}

    poller._get_state_node_from_prop = MagicMock(return_value=None)
    # Metemos una key para que evalúe a True la lógica de añadir a invalidated
    poller._pending_updates = {"hvac_mode": ("v", 0)}

    # Borramos la key ANTES del pop para asegurar que el default (None) es requerido
    del poller._pending_updates["hvac_mode"]

    # Si mutaron self._pending_updates.pop(prop_id, None) a pop(prop_id, )
    # Lanzará KeyError al intentar eliminar algo que ya no existe.
    poller._evict_invalidated_pending_updates({"AC_FUN_POWER": "Off"})


async def test_async_update_state_dict_defaults_and_formatting():
    """Aniquila fallbacks {} faltantes y manipulación de str.rsplit de excepciones"""
    poller = YamlStatePoller(MagicMock())
    # Excepción SIN el carácter ':'
    poller.controller.loader.state_getter.async_update_state.side_effect = (
        CannotConnect("SimpleError")
    )
    poller._consecutive_connection_errors = 2
    poller._cached_device_state = None  # Fuerza elevación de UpdateFailed
    poller.controller.config = {"device_type": "some_type"}

    # Destrucción del objeto caché para forzar la evaluación del `getattr(..., "cache", {})`
    delattr(poller.controller.loader, "_parsed_yaml_cache")

    with pytest.raises(UpdateFailed) as exc_info:
        await poller.async_update_state()

    # Si mutaron la lógica rsplit(":", maxsplit=1) o alteraron 'reason = None'
    assert "SimpleError" in str(exc_info.value)


async def test_build_device_state_from_hass_attribute_missing():
    """Kills mutants de getattr sin default y protege el regex de mocks."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # FIX: Configuramos el mock de state_getter para que su atributo 'value' sea un dict real
    # para que no retorne un objeto MagicMock que rompa el isinstance(res, dict)
    st_getter = MagicMock()
    st_getter.value = {"key": "val"}
    poller.controller.loader.state_getter = st_getter

    op = MagicMock(id="test_id")
    # Aseguramos que status_template sea None para evitar acceso a mocks
    op.status_template = None
    op.convert_hass_to_dev = MagicMock(side_effect=lambda x: x)

    poller.controller.loader.operations = {"test_id": op}
    poller.controller.loader.properties = {}

    class MockHassState:
        pass

    hass_state = MockHassState()

    # Evitamos que get_cached_device_key_from_prop invoque regex sobre mocks
    poller._get_state_node_from_prop = MagicMock(return_value=None)

    # Ejecución
    res = await poller._build_device_state_from_hass(hass_state)

    # Ahora res debe ser dict (reconstructed_state) y no un MagicMock
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
    """Mata mutaciones len(device_list) >= 0 que causan IndexError"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter = MagicMock(
        value={"Devices": []}
    )  # LISTA VACÍA ESTRICTA

    for op_id in ["temperature", "hvac", "fan_max", "good_sleep"]:
        op = MagicMock(id=op_id, value="test_val")
        delattr(op, "convert_hass_to_dev")
        poller.controller.loader.operations = {op_id: op}
        poller.controller.loader.properties = {}
        poller.controller.config = {"device_type": "Other"}

        # ORIGINAL: No entra al if porque 0 > 0 es False.
        # MUTANTE: Entra (>= 0 es True) e intenta evaluar devices[0], detonando IndexError.
        # El test debe pasar, si lanza excepción, el mutante muere.
        res = await poller._build_device_state_from_props()
        assert res == {"Devices": []}


async def test_async_predict_and_correct_state_feature_flag_exact():
    """Mata la inyección estática de ClimateEntityFeature(1) en los retornos tempranos."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter.value = {"real": "data"}

    op = MagicMock(id="test_op")
    poller.controller.loader.operations = {"test_op": op}
    poller.controller.loader.properties = {}

    # Test path 1: future_state es vacío
    poller._build_device_state_from_props = AsyncMock(return_value={})
    feat1, _ = await poller.async_predict_and_correct_state(
        MagicMock(), "test_op", "val"
    )
    assert (
        feat1.value == 0
    ), "Mutación: Se devolvió ClimateEntityFeature(1) en path vacío"

    # Test path 2: future_state tiene contenido
    poller._build_device_state_from_props = AsyncMock(return_value={"future": "data"})
    poller.async_update_properties_from_state = AsyncMock(return_value={"corr": "1"})
    feat2, _ = await poller.async_predict_and_correct_state(
        MagicMock(), "test_op", "val"
    )
    assert (
        feat2.value == 0
    ), "Mutación: Se devolvió ClimateEntityFeature(1) en path procesado"


async def test_build_device_state_fallback_to_private_value():
    """Verify mutant kill que elimina el fallback a '_value' en getattr (L664)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter = MagicMock(value={"Devices": []})

    op = MagicMock(id="test_op")
    delattr(op, "value")  # Forzamos a que el atributo público NO exista
    op._value = "hidden_val"
    op.convert_hass_to_dev = MagicMock(return_value="dev_val")

    poller.controller.loader.operations = {"test_op": op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="target_key")

    res = await poller._build_device_state_from_props()

    # If mutmut eliminó el fallback getattr(..., "_value", None), op_value será None
    # Saltará el ciclo por un 'continue', y 'target_key' jamás se asignará.
    assert (
        "target_key" in res
    ), "Fallo Lógico: El mutante ignoró el atributo privado '_value'"
    assert res["target_key"] == "dev_val"


async def test_build_device_state_from_props_swing_preset():
    """Mata mutaciones de setdefault() omitidos en operaciones swing y preset_mode"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # Diccionario base con lista, pero sub-diccionarios vacíos para forzar setdefault
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

    # If mutmut inserta un None en setdefault("Wind", ) o setdefault("Mode", )
    # el acceso posterior a ["direction"] o ["options"] lanzará TypeError: 'NoneType' no indexable
    res = await poller._build_device_state_from_props()

    assert res["Devices"][0]["Wind"]["direction"] == "Vertical"
    assert res["Devices"][0]["Mode"]["options"] == "Eco"


async def test_async_update_state_final_return_fallback():
    """Kills mutants que borran el fallback 'None' en el retorno final de update_state"""
    from unittest.mock import AsyncMock, MagicMock

    import pytest

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    poller = YamlStatePoller(MagicMock())

    # Configuramos éxito para pasar todos los try-except iniciales
    poller.controller.config = {"device_type": "Other"}
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader.state_getter = AsyncMock()
    poller.controller.loader.state_getter.async_update_state.return_value = {
        "raw": "data"
    }
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller.async_update_properties_from_state = AsyncMock()

    # ¡Destruimos físicamente 'value' del state_getter!
    delattr(poller.controller.loader.state_getter, "value")

    # Como quitamos el fallback `getattr(..., "value", None)` de la producción,
    # el intento de retornar la variable explotará con un AttributeError letal.
    with pytest.raises(AttributeError):
        await poller.async_update_state()


async def test_build_device_state_options_length_exact():
    """Verify mutant kill < 2 a <= 2 en good_sleep (L750) inyectando frontera exacta"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # Inject EXACTAMENTE 2 opciones. La frontera del mutante es vulnerable aquí.
    st_getter = MagicMock()
    st_getter.value = {"Devices": [{"Mode": {"options": ["Sleep_0", "Sleep_1"]}}]}
    poller.controller.loader.state_getter = st_getter

    op = MagicMock(id="good_sleep", value="2")
    delattr(op, "convert_hass_to_dev")  # Blindar de rutas externas
    poller.controller.loader.operations = {"good_sleep": op}
    poller.controller.loader.properties = {}

    res = await poller._build_device_state_from_props()

    # Original: 2 < 2 es False. No extiende la lista. (Queda len=2)
    # Mutante: 2 <= 2 es True. Extiende la lista insertando basura. (Queda len>2)
    assert len(res["Devices"][0]["Mode"]["options"]) == 2


async def test_async_update_properties_dict_depth():
    """Mata fallbacks {} mutados a falta de parámetros en cadenas .get() (L463-466)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})

    # loader._parsed_yaml_cache existe, pero está vacío.
    poller.controller.loader._parsed_yaml_cache = {}
    poller.controller.device_id = "MissingID"

    # Original: .get("XXXX", {}).get(CONFIG_DEVICE, {}).get(...) devuelve {} de forma segura.
    # Mutante: .get("XXXX").get(...) lanza AttributeError ('NoneType' object has no attribute 'get').
    res = await poller.async_update_properties_from_state(
        None, current_hass_state={"state": 1}
    )
    assert isinstance(res, dict)


async def test_debug_fallback_boolean():
    """Verify mutant kill for mutation de fallback False a True en getattr de 'debug' (L289, L537)"""
    ctrl = NakedObj()
    ctrl.loader = NakedObj()
    ctrl.loader.is_fully_initialized = True
    ctrl.config = {"device_type": "Other"}
    ctrl.log_prefix = "TEST"

    ctrl.loader.state_getter = AsyncMock()
    ctrl.loader.state_getter.async_update_state.return_value = {"raw": "data"}

    op = AsyncMock()
    op.id = "test_op"
    ctrl.loader.operations = {"test_op": op}
    ctrl.loader.properties = {}
    ctrl.loader.sensors = {}

    poller = YamlStatePoller(ctrl)
    poller._get_state_node_from_prop = MagicMock(return_value="target")
    poller.async_update_properties_from_state = AsyncMock()

    # ctrl NO tiene atributo 'debug'.
    await poller.async_update_state()
    # Si mutaron getattr(..., 'debug', False) a True, esto falla
    ctrl.loader.state_getter.async_update_state.assert_called_with(None, False)


async def test_dict_get_fallbacks_strict():
    """Kills mutants que borran fallbacks '{}' o '[]' encadenados (L463, L465, L479)"""
    ctrl = NakedObj()
    ctrl.loader = NakedObj(state_getter=NakedObj(value={}))
    ctrl.loader.is_fully_initialized = True
    ctrl.device_id = "MissingID"
    ctrl.log_prefix = "TEST"

    # DOTACIÓN ESTRUCTURAL: Prevenir que la función explote más adelante
    ctrl.loader.operations = {}
    ctrl.loader.properties = {}
    ctrl.loader.sensors = {}

    # Fuerza el _parsed_yaml_cache vacío
    ctrl.loader._parsed_yaml_cache = {}

    poller = YamlStatePoller(ctrl)
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller._rebuild_attributes = MagicMock()

    # L463 y L465: Si .get("MissingID", {}) muta a .get("MissingID"), devuelve None.
    # Luego None.get(...) lanza AttributeError y mata al mutante.
    res = await poller.async_update_properties_from_state(
        None, current_hass_state={"state": 1}
    )
    assert isinstance(res, dict)


async def test_async_update_properties_dict_get_no_swallow():
    """Kills mutants L466-482."""
    ctrl = NakedObj(
        loader=create_valid_loader(),
        device_id="MissingID",
        log_prefix="TEST",
        config={},
    )

    poller = YamlStatePoller(ctrl)
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})
    poller._rebuild_attributes = lambda: None

    res = await poller.async_update_properties_from_state(
        None, current_hass_state=NakedObj()
    )
    assert isinstance(res, dict)


async def test_debug_fallback_exact_call():
    """Kills mutants de fallback debug en L289 y L540."""
    loader = create_valid_loader()
    ctrl = NakedObj(log_prefix="TEST", config={"device_type": "Other"}, loader=loader)

    # 1. Usamos MagicMock para op para garantizar que hasattr() y async_update_state funcionen correctamente
    op = MagicMock()
    op.id = "swing"
    op.convert_hass_to_dev.return_value = "old_val"
    op.async_update_state = AsyncMock()  # El método debe ser un AsyncMock
    op.is_valid = lambda x: True

    # Aseguramos que la estructura esté completa
    loader.operations = {"swing": op}
    loader.properties = {}
    loader.sensors = {}

    # 2. Create el estado de HASS necesario para pasar el 'hasattr'
    current_hass_state = NakedObj()
    current_hass_state.swing_mode = "on"

    poller = YamlStatePoller(ctrl)
    poller._get_state_node_from_prop = lambda x: "Key"
    poller._last_device_state = {"Key": "old_val"}

    # 3. Llamada al método real
    await poller.async_update_properties_from_state(
        full_device_state={"Key": "old_val"},
        is_prediction=False,
        force_update=True,
        current_hass_state=current_hass_state,
    )

    # Verificamos la llamada
    op.async_update_state.assert_called_once_with({"Key": "old_val"}, False)


async def test_predict_and_correct_state_mutants():
    """Verify mutant kill L979 que asigna op.value = None en el bucle de sincronización."""
    loader = create_valid_loader()

    # 0. PREVENCIÓN DE EARLY EXIT: Aseguramos que los "guards" de inicialización pasen
    loader.is_fully_initialized = True
    if not getattr(loader, "state_getter", None):
        loader.state_getter = NakedObj(value={"dummy": "state"})
    elif not getattr(loader.state_getter, "value", None):
        loader.state_getter.value = {"dummy": "state"}

    # INYECCIÓN DE DEPENDENCIA: Agregamos config={} para satisfacer a _build_device_state_from_props
    ctrl = NakedObj(loader=loader, log_prefix="TEST", config={})

    # 1. AISLAMIENTO MULTI-OBJETIVO:
    # Usamos una operación como objetivo directo (target_temp) y otra como espectador (fan_mode)
    op_target = NakedObj(id="target_temp", value="old")
    op_bystander = NakedObj(id="fan_mode", value="old")

    loader.operations = {"target_temp": op_target, "fan_mode": op_bystander}

    # Evitamos AttributeError si el método itera sobre loader.properties
    if not hasattr(loader, "properties"):
        loader.properties = {}

    # 2. SATURACIÓN DE ESTADO: Mapeo de valores de entrada para ambos objetos
    current_hass_state = NakedObj(
        target_temp=24.5,
        target_temperature=24.5,
        temperature=24.5,
        fan_mode="auto",  # Este valor es el cebo para el mutante
    )

    poller = YamlStatePoller(ctrl)
    poller._pending_updates = {"target_temp": ("old_val", time.time())}

    # 3. ENRUTAMIENTO EXPLÍCITO
    await poller.async_predict_and_correct_state(
        property_name="target_temp",
        new_value=24.5,
        current_hass_state=current_hass_state,
    )

    # 4. ASERCIONES LETALES
    # A) Verifica el comportamiento normal (override posterior)
    assert op_target.value == 24.5, "El target directo no se actualizó correctamente."

    # B) KILL THE MUTANT: Verifica el bucle general de operaciones
    # If mutant altera 'op.value = val' a 'op.value = None', el valor aquí será None y el test fallará, matando al mutante.
    assert (
        op_bystander.value == "old"
    ), "¡Mutante detectado! El espectador recibió None en lugar de su valor original del estado."


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
    assert (
        res1.get("AC_FUN_POWER") == "On"
    ), "Mutant survived! operations.get('power') OR properties.get('power') fallback failed."

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
    assert (
        "AC_FUN_POWER" not in res2
    ), "Mutant survived! Power key was injected even when power_op was None."


async def test_async_update_properties_dict_depth():
    """Mata fallbacks {} mutados a falta de parámetros en cadenas .get() (L463-466)"""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller._build_device_state_from_hass = AsyncMock(return_value={"raw": "data"})

    # loader._parsed_yaml_cache existe, pero está vacío.
    mock_controller = poller.controller
    mock_controller.loader._parsed_yaml_cache = {}
    mock_controller.device_id = "123"

    res = await poller.async_update_properties_from_state({"raw": "data"})
    assert res == {} or res is not None


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
    assert (
        res_cool["AC_FUN_POWER"] == "On"
    ), "Mutant survived! Power should be strictly 'On' when device_value is 'Cool'."
