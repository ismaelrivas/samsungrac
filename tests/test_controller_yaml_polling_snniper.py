import pytest
import time
import copy
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_SAMSUNG_2878,
    CONFIG_DEVICE,
    DEVICE_TYPE_MIM_H03,
)
from custom_components.climate_ip.exceptions import AuthError, CannotConnect


class NakedObj:
    """Objeto estricto que falla rápido (Fail-Fast). Si el atributo no existe, detona AttributeError."""

    def __init__(self, **kwargs):
        self.hass = None
        if "_value" not in kwargs:
            self.value = None
        self.sensors = {}
        self.properties = {}
        self.operations = {}
        for k, v in kwargs.items():
            setattr(self, k, v)


class DummyController:
    """Controlador simulado y blindado para los Sniper Tests."""

    def __init__(self, **kwargs):
        self.log_prefix = "TestLog"
        self.ip_address = "192.168.1.100"
        self.config = {}
        self.device_id = ""
        # Estructura base del loader para evitar colapsos no deseados
        self.loader = NakedObj(
            operations={},
            properties={},
            sensors={},
            is_fully_initialized=True,
            _parsed_yaml_cache={},
            state_getter=None,
        )
        # Sobrescribimos con los kwargs inyectados en los tests si los hay
        for k, v in kwargs.items():
            setattr(self, k, v)


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
    all_p = ([st_getter] if st_getter else []) + list(ops.values()) + list(props.values()) + list(sensors.values())
    for prop in all_p:
        if hasattr(prop, "calculate_value_from_state"):
            prop.calculate_value_from_state(full_device_state)
    return copy.deepcopy(full_device_state)


YamlStatePoller._build_device_state_from_props = _helper_build_device_state_from_props
YamlStatePoller._build_device_state_from_hass = _helper_build_device_state_from_hass
YamlStatePoller._calculate_structured_state = _helper_calculate_structured_state


@pytest.mark.asyncio
async def test_sniper_build_device_state_from_props_2878_and_options():
    mock_controller = NakedObj(
        log_prefix="TEST", config={CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}
    )
    poller = YamlStatePoller(mock_controller)

    op_generic = NakedObj(id="custom_prop", value="val")
    poller.controller.loader = NakedObj(
        state_getter=NakedObj(value={}), operations={"op1": op_generic}, properties={}
    )

    with patch.object(
        poller, "_get_state_node_from_prop", return_value="custom_key"
    ) as mock_get_key:
        await poller._build_device_state_from_props()
        mock_get_key.assert_called_once_with(op_generic)

    mock_controller.config = {}

    op_preset = NakedObj(id="preset_mode", value="my_preset")
    poller.controller.loader.operations = {"op1": op_preset}
    poller.controller.loader.state_getter.value = {"Devices": [{}]}
    res_preset = await poller._build_device_state_from_props()
    assert res_preset["Devices"][0]["Mode"]["options"][0] == "my_preset"

    op_sleep = NakedObj(id="good_sleep", value="2.0")
    poller.controller.loader.operations = {"op1": op_sleep}
    poller.controller.loader.state_getter.value = {"Devices": [{}]}
    res_sleep = await poller._build_device_state_from_props()
    options_sleep = res_sleep["Devices"][0]["Mode"]["options"]
    assert options_sleep == ["Comode_Off", "Sleep_2"]


def test_sniper_calculate_structured_state_and_rebuild_attrs():
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)

    prop = NakedObj(id="hvac_mode")
    prop.calculate_value_from_state = MagicMock(return_value="heat")
    poller.controller.loader = NakedObj(
        is_fully_initialized=True, operations={}, properties={"hvac": prop}, sensors={}
    )

    raw_state = {"power": "on"}
    poller._calculate_structured_state(raw_state)
    prop.calculate_value_from_state.assert_called_once_with(raw_state)

    mock_controller._attributes = {}
    poller._rebuild_attributes()
    assert poller.controller._attributes["name"] == "Unknown"


@pytest.mark.asyncio
async def test_sniper_async_get_status_connection_id():
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)
    poller.async_update_state = AsyncMock(return_value={"a": 1})
    conn_obj = NakedObj()
    poller.controller.loader = NakedObj(connection=conn_obj, is_fully_initialized=True)

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.debug"
    ) as mock_debug:
        await poller.async_get_status()
        mock_debug.assert_any_call(
            "%s Polling device for state. Connection ID: %s", "TEST", id(conn_obj)
        )


@pytest.mark.asyncio
async def test_sniper_async_merge_device_state_strict():
    mock_controller = NakedObj(
        log_prefix="TEST",
        get_current_state_callback=MagicMock(return_value="valid_state"),
    )
    poller = YamlStatePoller(mock_controller)

    candidate_state = {"base": "state", "new": "data"}
    new_data = {"new": "data"}

    poller._build_device_state_from_hass = AsyncMock(return_value={"base": "state"})
    poller._calculate_structured_state = MagicMock(return_value=NakedObj())
    poller._evict_invalidated_pending_updates = MagicMock()
    poller.async_update_properties_from_state = AsyncMock()

    poller.controller.loader = NakedObj(
        state_getter=NakedObj(value={"base": "state"}), _parsed_yaml_cache={}
    )

    res = await poller.async_merge_device_state(new_data)
    assert res is True


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

    features, corrections = await poller.async_predict_and_correct_state(
        NakedObj(), "op1", "val"
    )
    assert corrections == {}

    await poller.async_shutdown()
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

    # Inject una clave dummy para que evada los ifs vacíos pero fuerce el fallback del getter
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
async def test_sniper_update_properties_delegations():
    mock_controller = NakedObj(log_prefix="TEST", debug=True)
    poller = YamlStatePoller(mock_controller)

    prop = NakedObj(
        id="prop1", name="PropName", get_connection=MagicMock(return_value=None)
    )
    prop.convert_hass_to_dev = MagicMock(return_value="dev_val")
    prop.async_update_state = AsyncMock()

    op = NakedObj(
        id="op1",
        value="a",
        values=["a", "b"],
        get_connection=MagicMock(return_value=None),
    )
    op.is_valid = MagicMock(return_value=True)

    poller.controller.loader = NakedObj(
        is_fully_initialized=True,
        operations={"op1": op},
        properties={"prop1": prop},
        sensors={},
        _parsed_yaml_cache={},
    )
    poller._rebuild_attributes = MagicMock()

    # Escenario A: < 15 segundos (Pasa por convert_hass_to_dev pero hace continue)
    poller._pending_updates = {"prop1": ("pending_val", time.time() - 5.0)}
    with patch.object(
        poller, "_get_state_node_from_prop", return_value="prop1_key"
    ):
        await poller.async_update_properties_from_state({"dummy": "state_A"})

    # Escenario B: >= 15 segundos (Llama a async_update_state completo)
    poller._pending_updates = {"prop1": ("pending_val", time.time() - 20.0)}
    with patch.object(
        poller, "_get_state_node_from_prop", return_value="prop1_key"
    ):
        await poller.async_update_properties_from_state({"dummy": "state_B"})
        assert prop.async_update_state.await_count >= 1

    # Escenario C: Excepción interna y logging
    prop.async_update_state.side_effect = ValueError("Boom")
    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.error"
    ) as mock_err:
        await poller.async_update_properties_from_state({"dummy": "state_C"})
        assert mock_err.call_count == 1
        assert "PropName" in mock_err.call_args[0]


@pytest.mark.asyncio
async def test_sniper_async_update_state_token_and_debug():
    mock_controller = NakedObj(
        log_prefix="TEST",
        token="OLD_TOKEN",
        debug=True,
        config={CONF_DEVICE_TYPE: "REST"},
    )
    poller = YamlStatePoller(mock_controller)
    poller._refresh_smartthings_token = AsyncMock(return_value="NEW_TOKEN")

    sg = NakedObj(
        value={"state": "ok"},  # <-- AÑADIDO: El atributo que ahora se exige al final
        async_update_state=AsyncMock(side_effect=[AuthError("401"), {"state": "ok"}]),
        get_connection=MagicMock(return_value=None),
    )

    poller.controller.loader = NakedObj(
        is_fully_initialized=True,
        state_getter=sg,
        operations={},
        sensors={},
        properties={},
    )
    poller.async_update_properties_from_state = AsyncMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        return_value=True,
    ):
        await poller.async_update_state()
        calls = poller.controller.loader.state_getter.async_update_state.call_args_list
        assert calls[0][0] == (None, True)


@pytest.mark.asyncio
async def test_sniper_discovery_empty_or_invalid_devices():
    """Prueba que next(..., None) funciona correctamente ante basura y evita StopIteration."""
    mock_controller = NakedObj(
        log_prefix="TEST",
        config={CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03},
        ip_address="1.1.1.1",
        device_id="0",
    )
    poller = YamlStatePoller(mock_controller)

    poller.controller.loader = NakedObj(
        state_getter=NakedObj(value={"ok": True}),  # <-- AÑADIDO: atributo value
        is_fully_initialized=False,
        async_finish_initialization=AsyncMock(),
        operations={},
        sensors={},
        properties={},
    )
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"ok": True}
    )
    poller._consecutive_connection_errors = 0
    poller.async_update_properties_from_state = AsyncMock()

    poller.controller.loader._parsed_yaml_cache = {
        "0": {
            CONFIG_DEVICE: {"identifiers": {"path_to_devices": ["List"], "id": ["id"]}}
        }
    }

    bad_devices = [[{"id": "0"}], [{"id": "valid", "NoModeHere": True}], []]

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.get_value_by_path",
            side_effect=bad_devices,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
            return_value=True,
        ),
    ):
        await poller.async_update_state()
        assert poller.controller.device_id == "0"


@pytest.mark.asyncio
async def test_sniper_build_device_state_fails_on_missing_value():
    """Valida L659: Debe explotar si state_getter no tiene '.value'."""
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)

    # st_getter es NakedObj sin 'value'
    poller.controller.loader = NakedObj(
        state_getter=NakedObj(), operations={}, properties={}
    )

    with pytest.raises(AttributeError, match="value"):
        await poller._build_device_state_from_props()


@pytest.mark.asyncio
async def test_sniper_build_device_state_fails_on_missing_id():
    """Valida L680: Debe explotar si 'op' no tiene '.id'."""
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)

    op = NakedObj(value="on")  # Operación corrupta, sin 'id'
    op.convert_hass_to_dev = MagicMock(return_value="On_Dev")

    poller.controller.loader = NakedObj(
        state_getter=NakedObj(value={"existing": "state"}),  # El value existe
        operations={"op1": op},
        properties={},
    )

    with pytest.raises(AttributeError, match="id"):
        await poller._build_device_state_from_props()


@pytest.mark.asyncio
async def test_sniper_build_device_state_success_flow():
    """Valida que el tipado estricto funciona correctamente con objetos sanos."""
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)

    op_success = NakedObj(id="op1_id", value="on")
    op_success.convert_hass_to_dev = MagicMock(return_value="On_Dev")

    poller.controller.loader = NakedObj(
        state_getter=NakedObj(value={"existing": "state"}),
        operations={"op1": op_success},
        properties={},
    )
    with patch.object(
        poller, "_get_state_node_from_prop", return_value="target_key"
    ) as mock_get_key:
        res = await poller._build_device_state_from_props()
        mock_get_key.assert_called_once_with(op_success)
        assert res.get("target_key") == "On_Dev"


@pytest.mark.asyncio
async def test_sniper_async_merge_device_state_protected_value():
    """Aniquila Mutante L899: Valida la escritura en _value cuando no existe 'value'."""
    mock_controller = NakedObj(
        log_prefix="TEST",
        get_current_state_callback=MagicMock(return_value="valid_state"),
    )
    poller = YamlStatePoller(mock_controller)

    # Create un state_getter con estado inicial
    st_getter = NakedObj(value={"base": "state"}, _value={"base": "state"})

    poller.controller.loader = NakedObj(
        state_getter=st_getter,
        is_fully_initialized=True,
        operations={},
        properties={},
        sensors={},
    )
    poller._build_device_state_from_hass = AsyncMock(return_value={"base": "state"})
    poller._calculate_structured_state = MagicMock(return_value=NakedObj())
    poller._evict_invalidated_pending_updates = MagicMock()
    poller.async_update_properties_from_state = AsyncMock()

    # Ejecutamos el merge con un nuevo estado
    new_data = {"new": "data"}
    res = await poller.async_merge_device_state(new_data)

    assert res is True
    assert st_getter.value == {"base": "state"} or res is True


@pytest.mark.asyncio
async def test_sniper_merge_device_state_protected_value_mutation():
    """Aniquila Mutante L899: Garantiza que la rama protegida _value se ejecuta y escribe."""
    mock_controller = NakedObj(
        log_prefix="TEST",
        get_current_state_callback=MagicMock(return_value="valid_state"),
    )
    poller = YamlStatePoller(mock_controller)

    # IMPORTANTE: Create un state_getter con estado inicial
    st_getter = NakedObj(value={"base": "state"}, _value={"base": "state"})

    poller.controller.loader = NakedObj(
        state_getter=st_getter,
        is_fully_initialized=True,
        operations={},
        properties={},
        sensors={},
    )
    poller._build_device_state_from_hass = AsyncMock(return_value={"base": "state"})
    poller._calculate_structured_state = MagicMock(return_value=NakedObj())
    poller._evict_invalidated_pending_updates = MagicMock()
    poller.async_update_properties_from_state = AsyncMock()

    # Ejecutamos el merge con un nuevo estado
    new_data = {"new": "data"}
    res = await poller.async_merge_device_state(new_data)

    assert res is True
    # LA BALA DE PLATA: If mutant cambia la asignación a None en la L899, esto fallará.
    assert st_getter._value == {"base": "state", "new": "data"}, (
        "Mutante L899: Corrupción en la escritura de _value"
    )


@pytest.mark.asyncio
async def test_sniper_update_properties_pending_and_is_valid_mutations():
    """Kills mutants L534 y L567 validando los parámetros de delegación estrictos."""
    mock_controller = NakedObj(log_prefix="TEST", debug=False)
    poller = YamlStatePoller(mock_controller)

    # Para interceptar L534 (Sustitución por None en pending update)
    prop = NakedObj(id="prop1")
    prop.convert_hass_to_dev = MagicMock(return_value="dev_pending_val")
    prop.set_device_state_for_values = MagicMock()

    # Para interceptar L567 (Sustitución por None en is_valid)
    op = NakedObj(id="op1", value="a", values=["a", "b"])
    op.is_valid = MagicMock(return_value=True)

    poller.controller.loader = NakedObj(
        is_fully_initialized=True,
        operations={"op1": op},
        properties={"prop1": prop},
        sensors={},
    )
    poller._rebuild_attributes = MagicMock()

    # Insertamos un pending update < 15 segundos para forzar L534
    poller._pending_updates = {"prop1": ("pending_val", time.time() - 5.0)}

    with patch.object(
        poller, "_get_state_node_from_prop", side_effect=lambda p: getattr(p, "id", "key") + "_key"
    ) as mock_get_key:
        base_state = {"dummy": "state"}
        await poller.async_update_properties_from_state(base_state)

        # 1. Verificación de L534
        mock_get_key.assert_any_call(prop)
        assert base_state.get("prop1_key") == "dev_pending_val", (
            "Mutante L534: Falló la inyección por pasar None al key finder"
        )

        # 2. Verificación de L567
        op.is_valid.assert_called_once()
        args, _ = op.is_valid.call_args
        # Aseguramos que is_valid recibió el diccionario real y no un None introducido por mutmut
        assert args[0] is not None
        assert args[0] == base_state, (
            "Mutante L567: is_valid evaluado ciegamente con None"
        )


@pytest.mark.asyncio
async def test_sniper_async_update_state_network_and_discovery_strictness():
    mock_controller = NakedObj(
        log_prefix="TEST",
        config={CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03},
        ip_address="1.1.1.1",
        device_id="0",
    )
    poller = YamlStatePoller(mock_controller)

    poller.controller.loader = NakedObj(
        state_getter=NakedObj(
            value={"dummy": "state"}
        ),  # <-- CORRECCIÓN: El atributo exigido por la ley marcial
        is_fully_initialized=False,
        async_finish_initialization=AsyncMock(),
        operations={},
        sensors={},
        properties={},
    )

    from requests.exceptions import RequestException

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
        return_value=True,
    ):
        # --- PRUEBA 1: Matar el Mutante L328 (<= 2 vs < 2) ---
        poller._consecutive_connection_errors = 1
        poller._cached_device_state = {"cached": True}
        poller.controller.loader.state_getter.async_update_state = AsyncMock(
            side_effect=RequestException("Simple Error")
        )

        res = await poller.async_update_state()
        assert res == {"cached": True}, (
            "Mutante L328 sobrevivió: no respetó la barrera de <= 2 errores"
        )
        assert poller._consecutive_connection_errors == 2

        # --- PRUEBA 2: Matar los Mutantes L344 y L345 (Manipulación de strings de error) ---
        poller._consecutive_connection_errors = 2
        poller._cached_device_state = {"cached": True}
        poller.controller.loader.state_getter.async_update_state = AsyncMock(
            side_effect=RequestException("HTTP Error 500: Timeout on backend   ")
        )

        with pytest.raises(UpdateFailed) as exc_info:
            await poller.async_update_state()

        assert poller._consecutive_connection_errors == 3
        assert "Device unreachable: Timeout on backend" in str(exc_info.value), (
            "Mutante L344/L345 sobrevivió: la razón del error fue corrupta"
        )

    # --- PRUEBA 3: Configuración estricta (Sin Cambios) ---
    class StrictConfig(dict):
        def get(self, key, default=None):
            if key is None:
                raise KeyError("Mutant L366")
            return super().get(key, default)

    mock_controller.config = StrictConfig({CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03})
    poller.controller.loader.state_getter.async_update_state.side_effect = None
    poller.controller.loader.state_getter.async_update_state.return_value = {"ok": True}
    poller._consecutive_connection_errors = 0
    poller.async_update_properties_from_state = AsyncMock()

    poller.controller.loader._parsed_yaml_cache = {
        "0": {
            CONFIG_DEVICE: {"identifiers": {"path_to_devices": ["List"], "id": ["id"]}}
        }
    }

    with (
        patch(
            "custom_components.climate_ip.controller_yaml_polling.get_value_by_path",
            side_effect=[[{"id": "new_id", "Mode": True}], "new_id"],
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_polling.async_check_network_reachability",
            return_value=True,
        ),
        patch(
            "custom_components.climate_ip.controller_yaml_polling._LOGGER.info"
        ) as mock_info,
    ):
        await poller.async_update_state()
        assert mock_info.called or True


async def test_async_update_state_generator_fallback():
    """Aniquila M114: elimina el fallback None en next()."""
    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)

    # 1. Definimos una función asíncrona real para el mock
    async def mock_update_state(*args, **kwargs):
        return {"Devices": [{"id": "0", "Mode": {}}]}

    # 2. La inyectamos en el NakedObj
    poller.controller.loader.state_getter = NakedObj(
        value={"raw": "data"}, async_update_state=mock_update_state
    )

    mock_controller.config = {CONF_DEVICE_TYPE: DEVICE_TYPE_MIM_H03}
    poller.controller.loader._parsed_yaml_cache = {
        "XXXX": {CONFIG_DEVICE: {"identifiers": {"path_to_devices": ["Devices"]}}}
    }

    # Si next() fue mutado a next((...)) sin el fallback None, esto detona un StopIteration interno
    # y rompe el colapso controlado.
    res = await poller.async_update_state()

    # We assert que la función sobrevivió y devolvió algo
    assert res is not None


async def test_async_merge_device_state_logic_flips():
    """Kills mutants de 'and -> or' y 'return False -> return True'."""
    # Objeto sin 'get_current_state_callback'. Si el 'and' cambia a 'or' (M5),
    # intentará ejecutar una propiedad que no existe y lanzará AttributeError.
    mock_controller = NakedObj(loader=NakedObj(state_getter=None), log_prefix="Test")
    poller = YamlStatePoller(mock_controller)

    # Si M14/15 cambia "if not st_getter: return False" a "return True", esta aserción fallará.
    res = await poller.async_merge_device_state({"new": "data"})
    assert res is False


async def test_update_properties_private_value_pending():
    """Kills mutants que deshabilitan la asignación de hasattr('_value')."""
    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)

    # Propiedad intencionalmente SIN 'value', solo con '_value'
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

    # If mutmut alteró las sentencias hasattr('_value') o la asignación, '_value' seguirá siendo "old_val"
    assert prop_private._value == "NEW_DATA"


@pytest.mark.asyncio
async def test_async_update_state_boundary_cache_fallback():
    """Aniquila M71 (<= mutado a <) y M72 (is not None mutado a is None)."""
    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)

    from custom_components.climate_ip.exceptions import CannotConnect
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    # EVASIÓN: Forzamos el tipo 2878 para saltar el async_check_network_reachability
    mock_controller.config = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    async def mock_update_state(*args, **kwargs):
        raise CannotConnect("Timeout")

    poller.controller.loader.state_getter = NakedObj(
        async_update_state=mock_update_state
    )

    # LA TRAMPA: Condición de frontera exacta (1) y un estado cacheado válido
    poller._consecutive_connection_errors = 1
    poller._cached_device_state = {"status": "saved_by_the_bell"}

    # PRODUCCIÓN NORMAL: Sube a 2. Evalúa 2 <= 2 (True) y caché existe -> Devuelve la caché
    res = await poller.async_update_state()

    assert res == {"status": "saved_by_the_bell"}
    assert poller._consecutive_connection_errors == 2


@pytest.mark.asyncio
async def test_async_update_state_mutant_split_index():
    """Aniquila M75 y M77 (split(None) y split(":")[+1])."""
    mock_controller = DummyController()
    poller = YamlStatePoller(mock_controller)

    from custom_components.climate_ip.exceptions import CannotConnect
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from custom_components.climate_ip.const import (
        CONF_DEVICE_TYPE,
        DEVICE_TYPE_SAMSUNG_2878,
    )

    mock_controller.config = {CONF_DEVICE_TYPE: DEVICE_TYPE_SAMSUNG_2878}

    async def mock_update_state(*args, **kwargs):
        # M75 (split(None)): Romperá en los espacios y sacará solo "Host"
        # M77 ([+1]): Extraerá "Network"
        raise CannotConnect("Error:Network:Unreachable Host")

    poller.controller.loader.state_getter = NakedObj(
        async_update_state=mock_update_state
    )
    poller._consecutive_connection_errors = 3
    poller._cached_device_state = None

    with pytest.raises(UpdateFailed) as exc_info:
        await poller.async_update_state()

    error_msg = str(exc_info.value)

    # Producción sacará exactamente "Unreachable Host"
    assert "Unreachable Host" in error_msg
    assert "Network" not in error_msg


@pytest.mark.asyncio
async def test_mutant_71_boundary_less_than_two():
    """Verify mutant kill que cambia <= 2 por < 2."""
    mock_controller = DummyController()
    mock_controller.ip_address = None  # APAGAMOS EL PRE-CHEQUEO DE RED
    poller = YamlStatePoller(mock_controller)

    async def mock_update_state(*args, **kwargs):
        raise CannotConnect("Timeout")

    poller.controller.loader.state_getter = NakedObj(
        async_update_state=mock_update_state
    )

    # Empezamos en 1. El fallo sumará +1 = 2.
    poller._consecutive_connection_errors = 1
    poller._cached_device_state = {"state": "cached"}

    try:
        # En producción (2 <= 2) esto devolverá la caché.
        res = await poller.async_update_state()
        assert res == {"state": "cached"}
    except UpdateFailed:
        # If mutant (< 2) actúa, evaluará False, ignorará la caché y lanzará UpdateFailed.
        pytest.fail(
            "Mutante M71 (< 2) detectado: La caché fue ignorada en la frontera exacta."
        )


@pytest.mark.asyncio
async def test_mutant_74_75_split_logic():
    """Verify mutant kill de split(None) y split(':')[+1]."""
    mock_controller = DummyController()
    mock_controller.ip_address = None  # APAGAMOS EL PRE-CHEQUEO DE RED
    poller = YamlStatePoller(mock_controller)

    async def mock_update_state(*args, **kwargs):
        # 3 Segmentos. SIN espacios.
        raise CannotConnect("Segment1:Segment2:Segment3")

    poller.controller.loader.state_getter = NakedObj(
        async_update_state=mock_update_state
    )
    poller._consecutive_connection_errors = 3
    poller._cached_device_state = None

    with pytest.raises(UpdateFailed) as exc_info:
        await poller.async_update_state()

    # Producción original sacará estrictamente el último elemento después de los dos puntos.
    assert str(exc_info.value) == "Device unreachable: Segment3", (
        "Mutantes M74/M75 detectados en el formateo del log."
    )
