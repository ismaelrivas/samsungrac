import pytest
import time

from unittest.mock import MagicMock, AsyncMock, patch
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_UNKNOWN

from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller


# =====================================================================
# UTILIDADES TÁCTICAS RESCATADAS DEL MONOLITO
# =====================================================================
class NakedObj:
    """Objeto estéril sin magia de Mocks para evitar side-effects."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class DummyController(NakedObj):
    """Controlador simulado resistente a AttributeErrors."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not hasattr(self, "config"):
            self.config = {}
        if not hasattr(self, "log_prefix"):
            self.log_prefix = "TEST"
        if not hasattr(self, "ip_address"):
            self.ip_address = "127.0.0.1"
        if not hasattr(self, "loader"):
            self.loader = create_valid_loader()


def create_valid_loader():
    """Crea un loader mínimo que cumple con la Doctrina Estricta."""
    from unittest.mock import MagicMock

    loader = MagicMock()
    loader.is_fully_initialized = True
    loader.operations = {}
    loader.properties = {}
    loader.sensors = {}
    loader.state_getter = NakedObj(value={})  # <-- Atributo 'value' exigido
    return loader


# =====================================================================


async def test_update_properties_strict_subdevice_routing_and_logs():
    mock_controller = DummyController(log_prefix="TEST")
    if hasattr(mock_controller, "device_id"):
        delattr(mock_controller, "device_id")

    loader = create_valid_loader()
    mock_controller.loader = loader

    loader._parsed_yaml_cache = {
        "XXXX": {
            "device": {"identifiers": {"path_to_devices": ["List"], "id": ["dev_id"]}}
        }
    }

    full_state = {
        "List": [
            {"dev_id": "other", "value": "bad"},
            {"dev_id": "", "value": "target_hit"},
        ],
        "value": "missed_root",
    }

    # Atributo 'id' añadido para cumplir con el Tipado Estricto de L975/L986
    prop = NakedObj(id="test_prop", value="old")
    if hasattr(prop, "name"):
        delattr(prop, "name")

    prop.async_update_state = AsyncMock(side_effect=Exception("Boom"))
    loader.properties = {"test_prop": prop}

    poller = YamlStatePoller(mock_controller)

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.error"
    ) as mock_err:
        await poller.async_update_properties_from_state(full_state)

        prop.async_update_state.assert_awaited_once_with(
            {"dev_id": "", "value": "target_hit"}, False
        )

        mock_err.assert_called_once()
        log_args = mock_err.call_args[0]
        assert "unknown" in log_args


async def test_update_properties_dirty_check_logic_mutants():
    mock_controller = DummyController(log_prefix="TEST")
    loader = create_valid_loader()
    mock_controller.loader = loader
    poller = YamlStatePoller(mock_controller)
    poller._rebuild_attributes = MagicMock()

    state_a = {"val": 1}
    state_b = {"val": 2}

    poller._last_device_state = state_a.copy()

    res1 = await poller.async_update_properties_from_state(state_a.copy())
    assert res1 == {}
    poller._rebuild_attributes.assert_not_called()

    await poller.async_update_properties_from_state(state_a.copy(), force_update=True)
    poller._rebuild_attributes.assert_called_once()

    poller._rebuild_attributes.reset_mock()
    await poller.async_update_properties_from_state(state_a.copy(), is_prediction=True)
    poller._rebuild_attributes.assert_called_once()

    poller._rebuild_attributes.reset_mock()
    await poller.async_update_properties_from_state(state_b.copy())
    poller._rebuild_attributes.assert_called_once()

    poller._last_device_state = state_a.copy()
    poller._pending_updates = {"fake": ("val", time.time())}
    poller._rebuild_attributes.reset_mock()
    await poller.async_update_properties_from_state(state_a.copy())
    poller._rebuild_attributes.assert_called_once()


async def test_update_properties_operation_validation_fallbacks():
    mock_controller = DummyController(log_prefix="TEST")
    loader = create_valid_loader()
    mock_controller.loader = loader
    poller = YamlStatePoller(mock_controller)

    # Añadido atributo 'id' exigido por la arquitectura estricta
    op1 = NakedObj(
        id="op1",
        _value="invalid_mode",
        values=["auto", "cool"],
        _feature_flag=ClimateEntityFeature.FAN_MODE,
    )
    op1.is_valid = MagicMock(return_value=True)

    loader.operations = {"op1": op1}
    full_state = {"a": 1}

    corrections = await poller.async_update_properties_from_state(
        full_state, force_update=True
    )

    assert corrections == {"op1": "auto"}
    assert op1._value == "auto"
    assert poller.fan_modes_list_changed_pending_flicker is True

    poller.fan_modes_list_changed_pending_flicker = False
    op2 = NakedObj(id="op2", value=STATE_UNKNOWN, values=["auto"])
    op2.is_valid = MagicMock(return_value=True)
    loader.operations = {"op2": op2}

    corrections2 = await poller.async_update_properties_from_state(
        full_state, force_update=True
    )

    assert corrections2 == {}
    assert op2.value == STATE_UNKNOWN


async def test_async_update_properties_pending_ttl_and_degradation():
    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)

    mock_prop_valid = MagicMock()
    mock_prop_valid.id = "prop_valid"
    mock_prop_valid.convert_hass_to_dev.return_value = "dev_val_valid"
    poller._get_cached_device_key_from_prop = MagicMock(return_value="raw_key")

    mock_prop_stale = MagicMock()
    mock_prop_stale.id = "prop_stale"

    mock_prop_deg = MagicMock()
    mock_prop_deg.id = "prop_deg"
    mock_prop_deg.is_valid.return_value = True
    mock_prop_deg.value = "EstadoFalso"
    mock_prop_deg.values = ["Auto", "Cool"]

    mock_controller.loader.operations = {
        "prop_valid": mock_prop_valid,
        "prop_stale": mock_prop_stale,
        "prop_deg": mock_prop_deg,
    }
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    now = time.time()
    poller._pending_updates = {
        "prop_valid": ("ha_val_valid", now - 5.0),
        "prop_stale": ("ha_val_stale", now - 20.0),
    }

    fake_state = {"raw_key": "old_val"}
    corrections = await poller.async_update_properties_from_state(fake_state)

    assert "prop_stale" not in poller._pending_updates
    assert fake_state["raw_key"] == "dev_val_valid"
    assert mock_prop_deg.value == "Auto"
    assert corrections["prop_deg"] == "Auto"


async def test_async_update_properties_dirty_check():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.loader._parsed_yaml_cache = {}

    mock_prop = MagicMock()
    mock_prop.id = "hvac"
    mock_prop.template = None
    mock_prop.status_template = None
    mock_prop.async_update_state = AsyncMock()
    mock_controller.loader.operations = {"hvac": mock_prop}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    poller = YamlStatePoller(mock_controller)

    fake_state = {"power": "on"}
    poller._last_device_state = fake_state

    result = await poller.async_update_properties_from_state(fake_state)
    assert result == {}
    mock_prop.async_update_state.assert_not_called()

    result_pred = await poller.async_update_properties_from_state(
        fake_state, is_prediction=True, force_update=False
    )
    assert isinstance(result_pred, dict)
    mock_prop.async_update_state.assert_called_once()
    mock_prop.reset_mock()

    result_forced = await poller.async_update_properties_from_state(
        fake_state, is_prediction=False, force_update=True
    )
    assert isinstance(result_forced, dict)
    mock_prop.async_update_state.assert_called_once()
    mock_prop.reset_mock()

    poller._pending_updates = {"hvac": ("val", time.time())}
    result_pending = await poller.async_update_properties_from_state(
        fake_state, is_prediction=False, force_update=False
    )
    assert isinstance(result_pending, dict)
    mock_prop.async_update_state.assert_not_called()

    del poller._last_device_state
    poller._pending_updates = {}

    nested_state = {"Operation": {"power": "On"}}
    await poller.async_update_properties_from_state(nested_state)
    nested_state["Operation"]["power"] = "Off"

    assert poller._last_device_state["Operation"]["power"] == "On"


async def test_async_update_properties_sniper_signature_and_flags():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock

    class DummyProp:
        def __init__(self, name):
            self.id = name
            self.name = name
            self.value = None  # <-- AÑADIDO: Atributo exigido
            self.async_update_state = AsyncMock()

    class DummyLoader:
        def __init__(self):
            self.is_fully_initialized = True
            self.operations = {}
            self.properties = {"test_prop": DummyProp("test_prop")}
            self.sensors = {}
            self._parsed_yaml_cache = {}

    class DummyController:
        def __init__(self):
            self.log_prefix = "SNIPER"
            self.loader = DummyLoader()
            self.device_id = "test_dev"
            self.debug = False

    controller = DummyController()
    poller = YamlStatePoller(controller)
    mock_prop = controller.loader.properties["test_prop"]

    fake_state = {"power": "ON"}

    poller._last_device_state = {"power": "OFF"}
    await poller.async_update_properties_from_state(fake_state)
    assert poller._last_device_state == fake_state
    mock_prop.async_update_state.assert_called_once()

    mock_prop.async_update_state.reset_mock()
    result = await poller.async_update_properties_from_state(fake_state)
    assert result == {}
    mock_prop.async_update_state.assert_not_called()

    mock_prop.async_update_state.reset_mock()
    poller._last_device_state = {"power": "OLD"}

    await poller.async_update_properties_from_state(fake_state, is_prediction=True)
    assert poller._last_device_state == {"power": "OLD"}
    mock_prop.async_update_state.assert_called_once()

    mock_prop.async_update_state.reset_mock()
    poller._last_device_state = {"power": "ON"}
    await poller.async_update_properties_from_state(fake_state, force_update=True)
    mock_prop.async_update_state.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_properties_ttl():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock

    class MockProp:
        id = "wind_speed"
        value = "low"
        async_update_state = AsyncMock()
        convert_hass_to_dev = MagicMock(return_value="high_dev")

    mock_prop = MockProp()

    class FakeController:
        def __init__(self):
            class FakeLoader:
                is_fully_initialized = True
                operations = {"wind": mock_prop}
                properties = {}
                sensors = {}

            self.loader = FakeLoader()
            self.debug = False
            self.log_prefix = "test"

    mock_controller = FakeController()
    poller = YamlStatePoller(mock_controller)
    poller._get_cached_device_key_from_prop = MagicMock(return_value="WindLevel")

    device_payload = {"WindLevel": "low_dev"}

    with patch("time.time", return_value=100.0):
        poller._pending_updates = {"wind_speed": ("high", 86.0)}
        poller._last_device_state_str = "dirty"
        await poller.async_update_properties_from_state(device_payload)

        assert mock_prop.value == "high"
        mock_prop.async_update_state.assert_not_called()
        assert "wind_speed" in poller._pending_updates

    mock_prop.async_update_state.reset_mock()
    with patch("time.time", return_value=100.0):
        poller._pending_updates = {"wind_speed": ("high", 85.0)}
        poller._last_device_state_str = "dirty2"
        await poller.async_update_properties_from_state(device_payload)

        mock_prop.async_update_state.assert_called_once()
        assert "wind_speed" not in poller._pending_updates


@pytest.mark.asyncio
async def test_async_get_status_cache_ttl():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock, patch

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    poller.async_update_state = AsyncMock(return_value={"power": "on"})
    poller._cached_device_state = {"power": "on"}
    poller._last_state_fetch_time = 100.0

    with patch("time.time", return_value=102.0):
        await poller.async_get_status()
        poller.async_update_state.assert_called_once()

    poller.async_update_state.reset_mock()
    with patch("time.time", return_value=101.99):
        await poller.async_get_status()
        poller.async_update_state.assert_not_called()


async def test_async_update_properties_cache_get_chains():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock
    import pytest

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    mock_controller.device_id = "test_device"
    poller = YamlStatePoller(mock_controller)

    mock_controller.loader._parsed_yaml_cache = {"test_device": {}}

    try:
        res = await poller.async_update_properties_from_state({"raw": "data"})
        assert isinstance(res, dict)
    except AttributeError:
        pytest.fail("Fallback roto: el encadenamiento .get() falló.")

    mock_controller.loader._parsed_yaml_cache = {}

    try:
        res2 = await poller.async_update_properties_from_state({"raw": "data"})
        assert isinstance(res2, dict)
    except AttributeError:
        pytest.fail("Fallback roto: el encadenamiento .get() falló en la raíz.")


async def test_async_update_properties_loop_sequences_and_eviction_handling():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock
    import time

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)
    poller._get_cached_device_key_from_prop = MagicMock(return_value="power_key")

    class FakeProp:
        def __init__(self, id_val):
            self.id = id_val
            self.value = None  # <-- AÑADIDO
            self._value = None
            self.convert_hass_to_dev = MagicMock()
            self.async_update_state = AsyncMock()
            self.set_device_state_for_values = MagicMock()

    prop_active = FakeProp("active_prop")
    prop_active.convert_hass_to_dev.return_value = "dev_active"

    prop_stale = FakeProp("stale_prop")
    prop_standard = FakeProp("standard_prop")

    prop_no_convert = FakeProp("no_convert_prop")
    del prop_no_convert.convert_hass_to_dev

    all_props_list = [prop_active, prop_stale, prop_no_convert, prop_standard]
    mock_controller.loader.operations = {p.id: p for p in all_props_list}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    now = time.time()
    poller._pending_updates = {
        "active_prop": ("ha_active", now - 2.0),
        "stale_prop": ("ha_stale", now - 20.0),
        "no_convert_prop": ("ha_no_convert", now - 2.0),
    }

    fake_device_state = {"power_key": "original_value"}

    await poller.async_update_properties_from_state(
        fake_device_state, force_update=True
    )

    assert fake_device_state["power_key"] == "dev_active"
    assert prop_active.value == "ha_active" or prop_active._value == "ha_active"
    prop_active.async_update_state.assert_not_called()

    assert "stale_prop" not in poller._pending_updates
    prop_stale.async_update_state.assert_called_once_with(fake_device_state, False)
    prop_standard.async_update_state.assert_called_once_with(fake_device_state, False)

    for p in all_props_list:
        p.set_device_state_for_values.assert_called_once_with(fake_device_state)


async def test_async_update_properties_fan_flicker_flag():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from homeassistant.components.climate import ClimateEntityFeature

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)

    class FakeFanProp:
        def __init__(self):
            self.id = "fan_prop"
            self.value = "EstadoInvalido"
            self.values = ["Auto", "High"]
            self.feature_flag = ClimateEntityFeature.FAN_MODE

        def is_valid(self, state):
            return True

        def set_device_state_for_values(self, state):
            pass

    fake_fan = FakeFanProp()
    mock_controller.loader.operations = {"fan_prop": fake_fan}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    poller.fan_modes_list_changed_pending_flicker = False

    await poller.async_update_properties_from_state({"raw": "data"}, force_update=True)

    assert fake_fan.value == "Auto"
    assert poller.fan_modes_list_changed_pending_flicker is True


async def test_evict_invalidated_pending_updates():
    mock_controller = MagicMock()
    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.status_template = "{{ device_state.hvac_mode }}"
    mock_controller.loader.operations = {"hvac_mode": mock_op}

    poller = YamlStatePoller(mock_controller)
    poller._pending_updates["hvac_mode"] = ("heat", 123456789.0)

    poller._evict_invalidated_pending_updates({"hvac_mode": "cool"})
    assert len(poller._pending_updates) == 0

    poller._pending_updates["hvac_mode"] = ("heat", 123456789.0)
    poller._evict_invalidated_pending_updates({"AC_FUN_POWER": "Off"})
    assert len(poller._pending_updates) == 0


async def test_async_merge_device_state():
    mock_controller = MagicMock()
    mock_controller.get_current_state_callback.return_value = MagicMock()
    mock_getter = MagicMock()
    mock_getter.value = {"temperature": 20.0}  # <-- Existe el atributo
    mock_controller.loader.state_getter = mock_getter

    poller = YamlStatePoller(mock_controller)

    with (
        patch.object(
            poller, "_calculate_structured_state", return_value={"temp": 22.0}
        ),
        patch.object(
            poller, "async_update_properties_from_state", new_callable=AsyncMock
        ) as mock_update,
        patch.object(
            poller,
            "_build_device_state_from_hass",
            new_callable=AsyncMock,
            return_value={"temperature": 20.0},
        ),
    ):
        result = await poller.async_merge_device_state(
            {"temperature": 22.0}, False, False
        )

        assert result is True
        mock_update.assert_awaited_once()
        assert mock_getter.value == {"temperature": 22.0}


async def test_async_merge_device_state_edge_cases():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. Empty data
    assert await poller.async_merge_device_state({}, False, False) is False

    # 2. No state_getter (Fail-Fast -> AttributeError por acceso estricto en _build_device_state_from_hass)
    mock_controller.get_current_state_callback.return_value = None
    mock_controller.loader = NakedObj()  # Pelado, sin state_getter
    with pytest.raises(AttributeError):
        await poller.async_merge_device_state({"k": "v"}, False, False)

    # 3. State getter has no value (Fail-Fast -> AttributeError)
    mock_controller.loader.state_getter = NakedObj()  # Tiene getter, no tiene .value
    with pytest.raises(AttributeError):
        await poller.async_merge_device_state({"k": "v"}, False, False)

    # 4. State getter has value None -> returns False
    mock_controller.loader.state_getter = NakedObj(value=None)
    assert await poller.async_merge_device_state({"k": "v"}, False, False) is False

    # 5. Calculate structured returns None
    mock_controller.loader.state_getter = NakedObj(value={"k": "v"})
    with patch.object(poller, "_calculate_structured_state", return_value=None):
        assert (
            await poller.async_merge_device_state({"k2": "v2"}, False, False) is False
        )


async def test_update_props_pending_update_uvalue():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.discovered_devices = [{"id": "dev1"}]

    class DummyOp:
        pass

    prop_uvalue = DummyOp()
    prop_uvalue.id = "uprop"
    prop_uvalue.value = None  # <-- AÑADIDO
    prop_uvalue._value = "old"

    mock_controller.loader.properties = {"uprop": prop_uvalue}
    mock_controller.loader.operations = {}

    poller._pending_updates = {"uprop": ("new_val", time.time())}

    await poller.async_update_properties_from_state({"some": "state"})
    assert prop_uvalue.value == "new_val"


def test_get_hass_attr_for_op_id_unmocked():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    assert poller._get_hass_attr_for_op_id("hvac") == "hvac_mode"
    assert poller._get_hass_attr_for_op_id("unknown_op") == "unknown_op"


async def test_merge_device_state_atomic_merge():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    updates = {"c": 3}

    mock_controller.loader.properties = {}
    mock_controller.loader.operations = {}
    mock_controller.loader._parsed_yaml_cache = {}

    mock_controller.loader.state_getter = MagicMock()
    mock_controller.loader.state_getter.value = {"a": 1, "b": 2}

    hass_state_mock = MagicMock()
    mock_controller.get_current_state_callback = MagicMock(return_value=hass_state_mock)

    poller._calculate_structured_state = MagicMock(return_value=None)
    res_fail = await poller.async_merge_device_state(
        updates, _is_response=False, _is_update=True
    )
    assert res_fail is False

    poller._calculate_structured_state = MagicMock(return_value={"valid": True})
    res_succ = await poller.async_merge_device_state(
        updates, _is_response=False, _is_update=True
    )
    assert res_succ is True


async def test_merge_device_state_empty_and_overwrite():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    assert await poller.async_merge_device_state({}, False, False) is False

    mock_controller.get_current_state_callback = MagicMock(return_value=None)

    base_state = {"Untouched": {"nested": "A"}}

    class MockStateGetter:
        value = base_state

    mock_controller.loader.state_getter = MockStateGetter()
    poller._calculate_structured_state = MagicMock(return_value={"valid": True})
    poller.async_update_properties_from_state = AsyncMock()
    poller._evict_invalidated_pending_updates = MagicMock()

    new_data = {"NewKey": "B"}

    res = await poller.async_merge_device_state(new_data, False, False)
    assert res is True

    expected_state = {"Untouched": {"nested": "A"}, "NewKey": "B"}

    assert mock_controller.loader.state_getter.value == expected_state

    mock_controller.loader.state_getter.value["Untouched"]["nested"] = "Hacked"
    assert base_state["Untouched"]["nested"] == "A"


async def test_merge_device_state_strict_conditionals():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock, AsyncMock

    mock_controller = MagicMock()
    del mock_controller.get_current_state_callback
    poller = YamlStatePoller(mock_controller)

    # 1. No st_getter -> Fail Fast
    class StrictLoader:
        pass

    mock_controller.loader = StrictLoader()
    with pytest.raises(AttributeError):
        await poller.async_merge_device_state({"a": 1}, False, False)

    # 2. st_getter sin value -> Fail Fast
    class LoaderWithGetter:
        class StateGetter:
            pass

        state_getter = StateGetter()

    mock_controller.loader = LoaderWithGetter()
    with pytest.raises(AttributeError):
        await poller.async_merge_device_state({"a": 1}, False, False)

    # 3. current_hass_state is true -> uses _build_device_state_from_hass
    mock_controller.get_current_state_callback = MagicMock(
        return_value="mock_hass_state"
    )
    poller._build_device_state_from_hass = AsyncMock(return_value=None)

    assert await poller.async_merge_device_state({"a": 1}, False, False) is False
    poller._build_device_state_from_hass.assert_called_once_with("mock_hass_state")


async def test_update_properties_full_state_none():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock

    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    poller._build_device_state_from_hass = AsyncMock(return_value=None)

    res = await poller.async_update_properties_from_state(
        None, current_hass_state={"state": "on"}
    )
    assert res == {}


async def test_merge_device_state_st_getter_private_value():
    """Fuerza la línea donde st_getter carece intencionalmente de escritura para 'value' pero sí de lectura."""
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import AsyncMock, MagicMock

    mock_controller = MagicMock()
    # Para bypassear el acceso de lectura estricto, le damos get_current_state_callback
    mock_controller.get_current_state_callback = MagicMock(return_value="mocked_hass")

    # Este mock NO tiene .value asignable. Al intentar asignarlo fallará,
    # pero el flujo evaluará la variable protegida _value (Mutante 57).
    class MockGetter:
        def __init__(self):
            self._value = {}

    mock_controller.loader.state_getter = MockGetter()
    poller = YamlStatePoller(mock_controller)
    poller._build_device_state_from_hass = AsyncMock(return_value={"a": 1})
    poller._calculate_structured_state = MagicMock(return_value={"valid": True})
    poller.async_update_properties_from_state = AsyncMock()

    res = await poller.async_merge_device_state(
        {"b": 2}, _is_response=False, _is_update=True
    )
    assert res is True
    # Verificamos que cayó al fallback estricto _value de escritura
    assert mock_controller.loader.state_getter._value == {"a": 1, "b": 2}


def test_evict_invalidated_pending_updates_none_prop():
    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
    from unittest.mock import MagicMock

    mock_controller = MagicMock()
    mock_controller.loader.operations = {}
    mock_controller.loader.properties = {}

    poller = YamlStatePoller(mock_controller)
    poller._pending_updates = {"missing_prop_id": 12345}

    poller._evict_invalidated_pending_updates({"some_key": "val"})
    assert "missing_prop_id" in poller._pending_updates


async def test_async_update_properties_from_state_strict_logger():
    poller = YamlStatePoller(MagicMock())

    poller.controller.loader._parsed_yaml_cache = MagicMock()
    poller.controller.loader._parsed_yaml_cache.get.side_effect = Exception(
        "Inyección balística"
    )

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.error"
    ) as mock_log:
        await poller.async_update_properties_from_state({"Devices": [{}]})
        assert mock_log.call_args.kwargs.get("exc_info") is True

    op_mock = MagicMock(id="test_op")
    op_mock.value = None  # AÑADIDO
    op_mock.async_update_state = AsyncMock()
    poller._pending_updates = {"test_op": ("val", time.time() - 15.0)}
    poller.controller.loader.properties = {"test_op": op_mock}
    poller._get_cached_device_key_from_prop = MagicMock(return_value=None)

    poller.controller.debug = False

    await poller.async_update_properties_from_state({"Devices": [{}]})
    op_mock.async_update_state.assert_called_once()


async def test_evict_invalidated_updates_break_mutation():
    poller = YamlStatePoller(MagicMock())

    poller.controller.loader.operations = {"op1": None}
    prop_mock = MagicMock(id="prop_mock_id")
    poller.controller.loader.properties = {"prop2": prop_mock}

    poller._pending_updates = {"op1": ("val", 0), "prop2": ("val", 0)}
    poller._get_cached_device_key_from_prop = MagicMock(return_value="ValidKey")

    push_data = {"ValidKey": "trigger"}
    poller._evict_invalidated_pending_updates(push_data)

    assert "prop2" not in poller._pending_updates


def test_evict_invalidated_pending_updates_strict_logic():
    poller = YamlStatePoller(MagicMock())

    prop1 = MagicMock(id="op1")
    prop2 = MagicMock(id="op2")
    poller.controller.loader.operations = {"op1": prop1, "op2": prop2}
    poller.controller.loader.properties = {}

    poller._pending_updates = {"op1": ("v", 0), "op2": ("v", 0)}

    def mock_get_key(prop):
        return {"op1": "Key1", "op2": "Key2"}.get(prop.id)

    poller._get_cached_device_key_from_prop = MagicMock(side_effect=mock_get_key)

    push_data = {"Key2": "updated"}

    poller._evict_invalidated_pending_updates(push_data)

    assert "op1" in poller._pending_updates
    assert "op2" not in poller._pending_updates


async def test_async_merge_device_state_strict_args():
    poller = YamlStatePoller(MagicMock())

    st_getter = MagicMock()
    st_getter.value = {"base": "data"}
    poller.controller.loader.state_getter = st_getter
    poller.controller.get_current_state_callback = MagicMock(
        return_value="mock_hass_state"
    )

    with patch.object(
        poller, "async_update_properties_from_state", new_callable=AsyncMock
    ) as mock_update_props:
        res = await poller.async_merge_device_state({"new": "data"}, False, False)
        assert res is True

        mock_update_props.assert_called_once_with(
            {"base": "data", "new": "data"},
            force_update=True,
            current_hass_state="mock_hass_state",
        )


async def test_update_properties_from_state_break_mutation():
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True
    poller.controller.loader._parsed_yaml_cache = {}

    op_invalid = MagicMock(id="invalid_op")
    op_invalid.is_valid.return_value = False
    op_invalid.async_update_state = AsyncMock()
    op_invalid.value = None

    op_valid = MagicMock(id="target_op")
    op_valid.is_valid.return_value = True
    op_valid.async_update_state = AsyncMock()
    op_valid.value = "Turbo"
    op_valid.values = ["Low", "High"]

    poller.controller.loader.operations = {"op1": op_invalid, "op2": op_valid}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    poller._pending_updates = {}
    poller._rebuild_attributes = MagicMock()

    corrections = await poller.async_update_properties_from_state({"Devices": [{}]})

    assert "target_op" in corrections
    assert corrections["target_op"] == "Low"


async def test_async_update_properties_from_state_attribute_crashes():
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # Destrucción del caché en el loader (Forzando la caída silenciosa del getattr obsoleto)
    delattr(poller.controller.loader, "_parsed_yaml_cache")

    # Como hay un bloque try/except, atrapamos que no escale, pero loguea
    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.exception"
    ) as mock_exc:
        await poller.async_update_properties_from_state({"Devices": []})
        mock_exc.assert_called_once()


@patch("time.time", return_value=100.0)
async def test_update_properties_time_exact_boundary(mock_time):
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    poller._pending_updates = {"test_op": ("pending_val", 85.0)}

    op = MagicMock(id="test_op")
    op.value = None  # AÑADIDO
    op.convert_hass_to_dev = MagicMock()
    poller.controller.loader.operations = {"test_op": op}
    poller.controller.loader.properties = {}
    poller.controller.loader.sensors = {}
    poller._get_cached_device_key_from_prop = MagicMock(return_value="Key")

    await poller.async_update_properties_from_state(
        {"Key": "old_val"}, is_prediction=False
    )
    op.convert_hass_to_dev.assert_not_called()


def test_evict_invalidated_pending_updates_loop_mutations():
    poller = YamlStatePoller(MagicMock())

    op1 = MagicMock(id="prop1")
    op2 = MagicMock(id="prop2")
    op_hvac = MagicMock(id="hvac_mode")
    poller.controller.loader.operations = {
        "prop1": op1,
        "prop2": op2,
        "hvac_mode": op_hvac,
    }
    poller.controller.loader.properties = {}

    def mock_get_key(prop):
        return {"prop1": "Key1", "prop2": "Key2", "hvac_mode": "KeyHVAC"}.get(prop.id)

    poller._get_cached_device_key_from_prop = MagicMock(side_effect=mock_get_key)

    poller._pending_updates = {
        "prop1": ("v", 0),
        "prop2": ("v", 0),
        "hvac_mode": ("v", 0),
    }

    push_data = {"Key1": "data", "Key2": "data", "AC_FUN_POWER": "On"}
    poller._evict_invalidated_pending_updates(push_data)

    assert "prop2" not in poller._pending_updates
    assert "hvac_mode" in poller._pending_updates


async def test_async_merge_device_state_missing_getter():
    poller = YamlStatePoller(MagicMock())
    poller.controller.get_current_state_callback = MagicMock(return_value=None)

    # Destrucción estructural (Fail-Fast)
    delattr(poller.controller.loader, "state_getter")

    with pytest.raises(AttributeError):
        await poller.async_merge_device_state({"new": "data"}, False, False)
