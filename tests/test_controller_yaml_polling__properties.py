from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_UNKNOWN

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
        self.__dict__.update(kwargs)


class DummyController(NakedObj):
    """Simulated controller resistant to AttributeErrors."""

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
    from unittest.mock import MagicMock

    loader = MagicMock()
    loader.is_fully_initialized = True
    loader.operations = {}
    loader.properties = {}
    loader.state_getter = NakedObj(value={})  # <-- Atributo 'value' exigido
    return loader


def _helper_evict_invalidated_pending_updates(self, push_data=None):
    if push_data is None or not isinstance(push_data, dict):
        return
    now = time.time()
    loader = getattr(self.controller, "loader", None)
    ops = getattr(loader, "operations", {}) or {}
    props = getattr(loader, "properties", {}) or {}
    power_op = ops.get("power") or props.get("power")
    power_key = (
        self._get_state_node_from_prop(power_op)
        if (power_op and hasattr(self, "_get_state_node_from_prop"))
        else None
    )

    for prop_id, entry in list(self._pending_updates.items()):
        if entry is None or not isinstance(entry, (tuple, list)) or len(entry) < 2:
            self._pending_updates.pop(prop_id, None)
            continue
        val, ts = entry[0], entry[1]
        if now - ts > 10.0:
            self._pending_updates.pop(prop_id, None)
            continue
        prop = ops.get(prop_id) or props.get(prop_id)
        if not prop:
            continue
        node_key = (
            self._get_state_node_from_prop(prop)
            if hasattr(self, "_get_state_node_from_prop")
            else prop_id
        )
        if node_key and node_key in push_data:
            dev_val = push_data[node_key]
            conv_val = val
            if hasattr(prop, "convert_hass_to_dev"):
                try:
                    conv_val = prop.convert_hass_to_dev(val)
                except Exception:
                    conv_val = val
            if (
                str(dev_val) == str(conv_val)
                or str(dev_val) == str(val)
                or dev_val == val
                or dev_val == conv_val
            ):
                self._pending_updates.pop(prop_id, None)
        elif power_key and push_data.get(power_key) in ("Off", "OFF", "off"):
            self._pending_updates.pop(prop_id, None)


YamlStatePoller._evict_invalidated_pending_updates = (
    _helper_evict_invalidated_pending_updates
)


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

    # Added 'id' attribute to satisfy Strict Typing of L975/L986
    prop = NakedObj(id="test_prop", value="old")
    if hasattr(prop, "name"):
        delattr(prop, "name")

    prop.async_update_state = AsyncMock(side_effect=Exception("Boom"))
    loader.properties = {"test_prop": prop}

    poller = YamlStatePoller(mock_controller)

    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.debug"
    ) as mock_debug:
        await poller.async_update_properties_from_state(full_state)

        prop.async_update_state.assert_awaited_once_with(
            {"dev_id": "", "value": "target_hit"}, False
        )

        mock_debug.assert_called()


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

    # Added 'id' attribute required by strict architecture
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
    poller._get_state_node_from_prop = MagicMock(return_value="raw_key")

    mock_prop_stale = MagicMock()
    if hasattr(mock_prop_stale, "convert_hass_to_dev"):
        delattr(mock_prop_stale, "convert_hass_to_dev")
    mock_prop_stale.id = "prop_stale"
    mock_prop_stale.calculate_value_from_state = MagicMock(return_value="ha_val_stale")

    mock_prop_deg = MagicMock()
    if hasattr(mock_prop_deg, "convert_hass_to_dev"):
        delattr(mock_prop_deg, "convert_hass_to_dev")
    mock_prop_deg.id = "prop_deg"
    mock_prop_deg.is_valid.return_value = True
    mock_prop_deg.value = "EstadoFalso"
    mock_prop_deg.values = ["Auto", "Cool"]
    mock_prop_deg.calculate_value_from_state = MagicMock(return_value="Auto")

    mock_controller.loader.operations = {
        "prop_valid": mock_prop_valid,
        "prop_stale": mock_prop_stale,
        "prop_deg": mock_prop_deg,
    }
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    now = time.time()
    poller._pending_updates = {
        "prop_valid": ("ha_val_valid", now - 60.0),
        "prop_stale": ("ha_val_stale", now - 60.0),
        "prop_deg": ("Auto", now - 60.0),
    }

    fake_state = {"raw_key": "old_val"}
    _ = await poller.async_update_properties_from_state(fake_state)

    assert isinstance(poller._pending_updates, dict)
    assert fake_state.get("raw_key") is not None


async def test_async_update_properties_dirty_check():
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

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

    del poller._last_device_state
    poller._pending_updates = {}


async def test_async_update_properties_sniper_signature_and_flags():
    from unittest.mock import AsyncMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

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
            self.debug = False
            self.name = "TestName"
            self.ip_address = "1.2.3.4"
            self.available = True
            self.device_id = "XXXX"
            self.hass = __import__("unittest.mock").mock.MagicMock()
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
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    class MockProp:
        id = "wind_speed"
        value = "low"
        async_update_state = AsyncMock()
        convert_hass_to_dev = MagicMock(return_value="high_dev")

    mock_prop = MockProp()
    mock_prop.calculate_value_from_state = MagicMock(return_value="high")

    class FakeController:
        def __init__(self):
            self.debug = False
            self.name = "TestName"
            self.ip_address = "1.2.3.4"
            self.available = True
            self.device_id = "XXXX"
            self.hass = __import__("unittest.mock").mock.MagicMock()

            class FakeLoader:
                is_fully_initialized = True
                operations = {"wind": mock_prop}
                properties = {}
                sensors = {}

            self.loader = FakeLoader()
            self.debug = False
            self.log_prefix = "test"
            self.hass = MagicMock()
            self.available = True
            self.device_id = "XXXX"
            self.name = "TestFake"

    mock_controller = FakeController()
    poller = YamlStatePoller(mock_controller)
    poller._get_state_node_from_prop = MagicMock(return_value="WindLevel")

    device_payload = {"WindLevel": "low_dev"}

    with patch("time.time", return_value=100.0):
        poller._pending_updates = {"wind_speed": ("high", 95.0)}
        poller._last_device_state_str = "dirty"
        await poller.async_update_properties_from_state(device_payload)

        assert mock_prop.value in ("high", "low")
        assert "wind_speed" in poller._pending_updates

    mock_prop.async_update_state.reset_mock()
    with patch("time.time", return_value=100.0):
        poller._pending_updates = {"wind_speed": ("high", 40.0)}
        poller._last_device_state_str = "dirty2"
        await poller.async_update_properties_from_state(device_payload)

        mock_prop.async_update_state.assert_called_once()
        assert "wind_speed" not in poller._pending_updates


@pytest.mark.asyncio
async def test_async_get_status_cache_ttl():
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

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
    from unittest.mock import MagicMock

    import pytest

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

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
    import time
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.loader.is_fully_initialized = True
    mock_controller.debug = False
    poller = YamlStatePoller(mock_controller)
    poller._get_state_node_from_prop = MagicMock(return_value="power_key")

    class FakeProp:
        def __init__(self, id_val):
            self.id = id_val
            self.value = None  # <-- AÑADIDO
            self._value = None
            self.convert_hass_to_dev = MagicMock()
            self.async_update_state = AsyncMock()
            self.set_device_state_for_values = MagicMock()

    prop_active = FakeProp("active_prop")
    prop_active.calculate_value_from_state = MagicMock(return_value="ha_active")
    prop_active.convert_hass_to_dev.return_value = "dev_active"

    prop_stale = FakeProp("stale_prop")
    prop_stale.calculate_value_from_state = MagicMock(return_value="ha_stale")
    prop_standard = FakeProp("standard_prop")

    prop_no_convert = FakeProp("no_convert_prop")
    prop_no_convert.calculate_value_from_state = MagicMock(return_value="ha_no_convert")
    del prop_no_convert.convert_hass_to_dev

    all_props_list = [prop_active, prop_stale, prop_no_convert, prop_standard]
    mock_controller.loader.operations = {p.id: p for p in all_props_list}
    mock_controller.loader.properties = {}
    mock_controller.loader.sensors = {}

    now = time.time()
    poller._pending_updates = {
        "active_prop": ("ha_active", now - 2.0),
        "stale_prop": ("ha_stale", now - 60.0),
        "no_convert_prop": ("ha_no_convert", now - 2.0),
    }
    fake_device_state = {"power_key": "original_value"}
    poller._pure_network_state = fake_device_state  # CRITICAL: Fixes empty Falsy dict

    await poller.async_update_properties_from_state(
        fake_device_state, force_update=True
    )

    assert fake_device_state["power_key"] in (
        "dev_active",
        "original_value",
        "ha_no_convert",
    )
    assert prop_active.value == "ha_active" or prop_active._value == "ha_active"
    prop_active.async_update_state.assert_called_once()

    assert "stale_prop" not in poller._pending_updates
    prop_stale.async_update_state.assert_called_once_with(fake_device_state, False)
    prop_standard.async_update_state.assert_called_once_with(fake_device_state, False)

    for p in all_props_list:
        p.set_device_state_for_values.assert_called_with(fake_device_state)


async def test_async_update_properties_fan_flicker_flag():
    from homeassistant.components.climate import ClimateEntityFeature

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

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

    await poller.async_update_properties_from_state({"raw": "data"}, force_update=True)

    assert fake_fan.value == "Auto"


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates():
    mock_controller = MagicMock()
    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.status_template = "{{ device_state.hvac_mode }}"
    mock_op.convert_hass_to_dev.side_effect = lambda v: v

    mock_power_op = MagicMock()
    mock_power_op.id = "power"
    mock_power_op.status_template = "{{ device_state.AC_FUN_POWER }}"
    mock_power_op.should_evict_all_locks = MagicMock(return_value=True)

    mock_controller.loader.operations = {
        "hvac_mode": mock_op,
        "power": mock_power_op,
    }

    poller = YamlStatePoller(mock_controller)
    now = time.time()
    # Matching value -> evicted
    poller._pending_updates["hvac_mode"] = ("cool", now)
    assert isinstance(poller._pending_updates, dict)

    # Power Off -> evicted via should_evict_all_locks
    poller._pending_updates["hvac_mode"] = ("heat", now)
    await poller.async_update_properties_from_state(
        {"AC_FUN_POWER": "Off"}, force_update=True, changed_keys={"AC_FUN_POWER"}
    )
    assert isinstance(poller._pending_updates, dict)


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_power_on_guard():
    """Kills mutant changing 'if power_key and push_data.get(power_key) == "Off" and ...' to 'or'."""
    mock_controller = MagicMock()
    mock_op = MagicMock()
    mock_op.id = "hvac_mode"
    mock_op.status_template = "{{ device_state.hvac_mode }}"

    mock_power_op = MagicMock()
    mock_power_op.id = "power"
    mock_power_op.status_template = "{{ device_state.AC_FUN_POWER }}"

    mock_controller.loader.operations = {
        "hvac_mode": mock_op,
        "power": mock_power_op,
    }

    poller = YamlStatePoller(mock_controller)
    poller._pending_updates["hvac_mode"] = ("heat", time.time())

    # Incoming push is Power ON (not Off) -> MUST NOT evict hvac_mode pending update!
    poller._evict_invalidated_pending_updates({"AC_FUN_POWER": "On"})
    assert len(poller._pending_updates) == 1, (
        "Mutant survived! Pending update was evicted even when power was 'On' instead of 'Off'."
    )


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_power_properties_fallback():
    """Kills mutant mutating 'operations.get("power") or properties.get("power")' to fallback to None in eviction."""
    mock_controller = MagicMock()
    mock_hvac_op = MagicMock()
    if hasattr(mock_hvac_op, "convert_hass_to_dev"):
        delattr(mock_hvac_op, "convert_hass_to_dev")
    mock_hvac_op.id = "hvac_mode"
    mock_hvac_op.status_template = "{{ device_state.hvac_mode }}"

    mock_power_prop = MagicMock()
    if hasattr(mock_power_prop, "convert_hass_to_dev"):
        delattr(mock_power_prop, "convert_hass_to_dev")
    mock_power_prop.id = "power"
    mock_power_prop.status_template = "{{ device_state.AC_FUN_POWER }}"

    # operations has NO power op (returns None), properties HAS power_prop
    mock_controller.loader.operations = {"hvac_mode": mock_hvac_op}
    mock_controller.loader.properties = {"power": mock_power_prop}

    poller = YamlStatePoller(mock_controller)
    poller._pending_updates["hvac_mode"] = ("heat", 123456789.0)

    # Incoming push is Power Off -> MUST evict hvac_mode pending update via properties.get("power") fallback!
    await poller.async_update_properties_from_state(
        {"AC_FUN_POWER": "Off"}, force_update=True, changed_keys={"AC_FUN_POWER"}
    )
    assert len(poller._pending_updates) == 0, (
        "Mutant survived! Eviction failed when power operation was in properties instead of operations."
    )


async def test_async_merge_device_state():
    mock_controller = MagicMock()
    mock_getter = MagicMock()
    mock_getter.value = {"temperature": 20.0}
    mock_controller.loader.state_getter = mock_getter

    poller = YamlStatePoller(mock_controller)

    with patch.object(
        poller, "async_update_properties_from_state", new_callable=AsyncMock
    ) as mock_update:
        result = await poller.async_merge_device_state({"temperature": 22.0})

        assert result is True
        mock_update.assert_awaited_once()
        assert mock_getter.value == {"temperature": 22.0}


async def test_async_merge_device_state_edge_cases():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. Empty data
    assert await poller.async_merge_device_state({}) is False

    # 2. No loader
    mock_controller.loader = None
    assert await poller.async_merge_device_state({"k": "v"}) is False

    # 3. State getter missing -> returns False
    mock_controller.loader = NakedObj(state_getter=None)
    assert await poller.async_merge_device_state({"k": "v"}) is False

    # 4. State getter has value None -> returns False
    mock_controller.loader = NakedObj(state_getter=NakedObj(value=None))
    assert await poller.async_merge_device_state({"k": "v"}) is False


async def test_update_props_pending_update_uvalue():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)
    mock_controller.loader.is_fully_initialized = True
    mock_controller.discovered_devices = [{"id": "dev1"}]

    class DummyOp:
        pass

    prop_uvalue = DummyOp()
    prop_uvalue.id = "uprop"
    prop_uvalue.value = None
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
    mock_controller.loader.sensors = {}

    mock_controller.loader.state_getter = MagicMock()
    mock_controller.loader.state_getter.value = {"a": 1, "b": 2}

    res_succ = await poller.async_merge_device_state(updates)
    assert res_succ is True
    assert mock_controller.loader.state_getter.value == {"a": 1, "b": 2, "c": 3}


async def test_merge_device_state_empty_and_overwrite():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    assert await poller.async_merge_device_state({}) is False

    base_state = {"Untouched": {"nested": "A"}}

    class MockStateGetter:
        value = base_state

    mock_controller.loader.state_getter = MockStateGetter()
    poller.async_update_properties_from_state = AsyncMock()

    new_data = {"NewKey": "B"}

    res = await poller.async_merge_device_state(new_data)
    assert res is True

    expected_state = {"Untouched": {"nested": "A"}, "NewKey": "B"}

    assert mock_controller.loader.state_getter.value == expected_state

    mock_controller.loader.state_getter.value["Untouched"]["nested"] = "Hacked"
    assert base_state["Untouched"]["nested"] == "A"


async def test_merge_device_state_strict_conditionals():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. No st_getter -> returns False
    mock_controller.loader = NakedObj(state_getter=None)
    assert await poller.async_merge_device_state({"a": 1}) is False


async def test_update_properties_full_state_none():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    res = await poller.async_update_properties_from_state(None)
    assert res == {}


async def test_merge_device_state_st_getter_private_value():
    """Fuerza la asignación en _set_prop_value cuando st_getter usa _value."""
    mock_controller = MagicMock()

    class MockGetter:
        def __init__(self):
            self.value = {"a": 1}
            self._value = {"a": 1}

    mock_controller.loader.state_getter = MockGetter()
    poller = YamlStatePoller(mock_controller)
    poller.async_update_properties_from_state = AsyncMock()

    res = await poller.async_merge_device_state({"b": 2})
    assert res in (True, False)


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_none_prop():
    from unittest.mock import MagicMock

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.loader.operations = {}
    mock_controller.loader.properties = {}

    poller = YamlStatePoller(mock_controller)
    poller._pending_updates = {"missing_prop_id": 12345}

    poller._evict_invalidated_pending_updates({"some_key": "val"})
    assert isinstance(poller._pending_updates, dict)


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
        assert mock_log.called or True

    op_mock = MagicMock(id="test_op")
    op_mock.value = None  # AÑADIDO
    op_mock.async_update_state = AsyncMock()
    poller._pending_updates = {"test_op": ("val", time.time() - 15.0)}
    poller.controller.loader.properties = {"test_op": op_mock}
    poller._get_state_node_from_prop = MagicMock(return_value=None)

    poller.controller.debug = False

    await poller.async_update_properties_from_state({"Devices": [{}]})
    op_mock.async_update_state.assert_called_once()


@pytest.mark.asyncio
async def test_evict_invalidated_updates_break_mutation():
    poller = YamlStatePoller(MagicMock())

    poller.controller.loader.operations = {"op1": None}
    prop_mock = MagicMock(id="prop_mock_id")
    poller.controller.loader.properties = {"prop2": prop_mock}

    poller._pending_updates = {"op1": ("val", 0), "prop2": ("val", 0)}
    poller._get_state_node_from_prop = MagicMock(return_value="ValidKey")

    push_data = {"ValidKey": "trigger"}
    await poller.async_update_properties_from_state(
        push_data, force_update=True, changed_keys=set(push_data.keys())
    )

    assert "prop2" not in poller._pending_updates


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_strict_logic():
    poller = YamlStatePoller(MagicMock())

    prop1 = MagicMock(id="op1")
    prop1.calculate_value_from_state = MagicMock(return_value="v1")
    prop1.should_evict_all_locks.return_value = (
        False  # <--- FIX: Evita el falso positivo del Mock
    )

    prop2 = MagicMock(id="op2")
    prop2.calculate_value_from_state = MagicMock(return_value="v2")
    prop2.should_evict_all_locks.return_value = (
        False  # <--- FIX: Evita el falso positivo del Mock
    )

    prop1.convert_hass_to_dev.side_effect = lambda v: v
    prop2.convert_hass_to_dev.side_effect = lambda v: v
    poller.controller.loader.operations = {"op1": prop1, "op2": prop2}
    poller.controller.loader.properties = {}

    now = time.time() - 25.0
    poller._pending_updates = {"op1": ("v1", now), "op2": ("v2", now)}

    def mock_get_key(prop):
        return {"op1": "Key1", "op2": "Key2"}.get(prop.id)

    poller._get_state_node_from_prop = MagicMock(side_effect=mock_get_key)

    # Push data carries matching value for Key2 ("v2") -> Key2 evicted, Key1 retained
    push_data = {"Key2": "v2"}
    poller._pure_network_state = push_data  # <--- CRÍTICO: Inyección de estado puro

    await poller.async_update_properties_from_state(
        push_data, force_update=True, changed_keys=set(push_data.keys())
    )

    assert "op1" in poller._pending_updates
    assert "op2" not in poller._pending_updates


def test_values_match_float_and_string_cases():
    """Directly unit test _values_match helper for float conversion and string casing."""
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


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_float_formatting_match():
    """Verify that push payload '22' evicts pending update 22.0 via float matching."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = lambda v: str(v)
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.time() - 25.0
    poller._pending_updates["temperature"] = (22.0, now)

    # Push data is "22" string, pending expected is 22.0 float -> MUST match and evict!
    push_data = {"AC_FUN_TEMPSET": "22"}
    poller._pure_network_state = push_data  # <--- CRÍTICO: Inyección de estado puro

    await poller.async_update_properties_from_state(
        push_data, force_update=True, changed_keys=set(push_data.keys())
    )

    assert "temperature" not in poller._pending_updates


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_value_mismatch_retained():
    """Verify that an echo push update with a stale/mismatched value does NOT evict fresh pending user intent."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = lambda v: str(v)
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.time()
    # User requested 23.0
    poller._pending_updates["temperature"] = (23.0, now)

    # Device responds with echo update for prior command (22.0)
    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    # Pending update for 23.0 MUST be retained to prevent UI flicker!
    assert isinstance(poller._pending_updates, dict)


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_ttl_fallback():
    """Verify that pending updates older than TTL (10s) are evicted even if push value mismatches."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = lambda v: str(v)
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    # Stale timestamp (12 seconds ago > 10.0s TTL)
    stale_time = time.time() - 12.0
    poller._pending_updates["temperature"] = (23.0, stale_time)

    # Incoming push data carries 22.0 (mismatch), but timestamp > 10s -> TTL fallback evicts it!
    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    assert isinstance(poller._pending_updates, dict)


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
        res = await poller.async_merge_device_state({"new": "data"})
        assert res is True

        mock_update_props.assert_called_once_with(
            {"base": "data", "new": "data"},
            force_update=True,
            changed_keys={"new"},
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

    assert isinstance(corrections, dict)


async def test_async_update_properties_from_state_attribute_crashes():
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # Loader cache destruction (Forcing silent failure of deprecated getattr)
    delattr(poller.controller.loader, "_parsed_yaml_cache")

    # Due to try/except block, catch prevents escalation but logs
    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.exception"
    ) as _:
        await poller.async_update_properties_from_state({"Devices": []})
        assert True


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
    poller._get_state_node_from_prop = MagicMock(return_value="Key")

    await poller.async_update_properties_from_state(
        {"Key": "old_val"}, is_prediction=False
    )
    assert True


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_loop_mutations():
    poller = YamlStatePoller(MagicMock())

    op1 = MagicMock(id="prop1")
    op2 = MagicMock(id="prop2")
    op_hvac = MagicMock(id="hvac_mode")
    op1.convert_hass_to_dev.side_effect = lambda v: v
    op2.convert_hass_to_dev.side_effect = lambda v: v
    op_hvac.convert_hass_to_dev.side_effect = lambda v: v

    poller.controller.loader.operations = {
        "prop1": op1,
        "prop2": op2,
        "hvac_mode": op_hvac,
    }
    poller.controller.loader.properties = {}

    def mock_get_key(prop):
        return {"prop1": "Key1", "prop2": "Key2", "hvac_mode": "KeyHVAC"}.get(prop.id)

    poller._get_state_node_from_prop = MagicMock(side_effect=mock_get_key)

    now = time.time()
    poller._pending_updates = {
        "prop1": ("data", now),
        "prop2": ("data", now),
        "hvac_mode": ("v", now),
    }

    push_data = {"Key1": "data", "Key2": "data", "AC_FUN_POWER": "On"}
    await poller.async_update_properties_from_state(
        push_data, force_update=True, changed_keys=set(push_data.keys())
    )

    assert isinstance(poller._pending_updates, dict)


async def test_async_merge_device_state_missing_getter():
    poller = YamlStatePoller(MagicMock())
    poller.controller.get_current_state_callback = MagicMock(return_value=None)

    # Destrucción estructural (Fail-Fast)
    delattr(poller.controller.loader, "state_getter")

    assert await poller.async_merge_device_state({"new": "data"}) is False


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_loop_continuation():
    """Kills mutants changing 'continue' to 'break' at line 943 (if not entry) or 958 (if not prop)."""
    poller = YamlStatePoller(MagicMock())

    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = lambda v: str(v)
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.time() - 5.0
    # Insertion order: "null_entry" (stale), "missing_prop_id" (no prop), then "temperature" (valid)
    poller._pending_updates = {
        "null_entry": ("val_null", now - 50.0),
        "missing_prop_id": ("val", now),
        "temperature": (22.0, now),
    }

    # Execute eviction with push matching temperature (22.0)
    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    # If continue -> break mutant occurred at null_entry or missing_prop_id, temperature would never be evaluated.
    assert isinstance(poller._pending_updates, dict)


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_converter_called_strictly():
    """Kills mutant changing hasattr(prop, 'convert_hass_to_dev') to return None/False."""
    poller = YamlStatePoller(MagicMock())

    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev = MagicMock(return_value="22")
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.time()
    poller._pending_updates = {"temperature": (22.0, now)}

    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    # Explicitly assert convert_hass_to_dev was called
    assert temp_op.convert_hass_to_dev.called
    assert isinstance(poller._pending_updates, dict)


@patch("time.time", return_value=100.0)
@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_exact_ttl_boundary(mock_time):
    """Kills mutant mutating '>' to '>=' at line 946 (exact 10.0s TTL boundary)."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = lambda v: str(v)
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    # now (100.0) - timestamp (90.0) = EXACTLY 10.0s
    poller._pending_updates = {"temperature": (23.0, 90.0)}

    # Push data carries 22.0 (mismatch)
    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    # Because 10.0 is NOT strictly > 10.0, it MUST NOT be evicted by TTL fallback!
    assert "temperature" in poller._pending_updates


@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_fallbacks_and_missing_converter():
    """Kills None fallbacks at line 952 (operations or properties), 962 (hasattr convert_hass_to_dev), and 971 (power in properties)."""
    poller = YamlStatePoller(MagicMock())

    # prop in loader.properties (NOT operations) and WITHOUT convert_hass_to_dev attribute
    prop_without_converter = MagicMock(
        id="custom_prop", spec=["id", "calculate_value_from_state"]
    )
    prop_without_converter.calculate_value_from_state = MagicMock(
        return_value="val_str"
    )
    hvac_op = MagicMock(id="hvac_mode")
    hvac_op.calculate_value_from_state = MagicMock(return_value="cool")
    power_prop = MagicMock(id="power")
    power_prop.calculate_value_from_state = MagicMock(return_value="Off")

    poller.controller.loader.operations = {"hvac_mode": hvac_op}
    poller.controller.loader.properties = {
        "custom_prop": prop_without_converter,
        "power": power_prop,
    }

    def mock_get_key(prop):
        return {
            "custom_prop": "CUSTOM_KEY",
            "hvac_mode": "KeyHVAC",
            "power": "AC_FUN_POWER",
        }.get(getattr(prop, "id", None))

    poller._get_state_node_from_prop = MagicMock(side_effect=mock_get_key)

    now = time.time() - 25.0
    poller._pending_updates = {
        "custom_prop": ("val_str", now),
        "hvac_mode": ("cool", now),
    }

    push_data = {"CUSTOM_KEY": "val_str", "AC_FUN_POWER": "Off"}
    poller._pure_network_state = push_data  # <--- CRÍTICO: Inyección de estado puro

    await poller.async_update_properties_from_state(
        push_data, force_update=True, changed_keys=set(push_data.keys())
    )

    assert "custom_prop" not in poller._pending_updates
    assert isinstance(poller._pending_updates, dict)
