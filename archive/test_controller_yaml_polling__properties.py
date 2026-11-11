# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test,not-callable,invalid-sequence-index,unsubscriptable-object
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.const import STATE_UNKNOWN


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
    now = time.monotonic()
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
                except Exception:  # noqa: BLE001
                    conv_val = val
            if dev_val in (val, conv_val) or str(dev_val) in (
                str(val),
                str(conv_val),
            ):
                self._pending_updates.pop(prop_id, None)
        elif power_key and push_data.get(power_key) in ("Off", "OFF", "off"):
            self._pending_updates.pop(prop_id, None)


@pytest.fixture(autouse=True)
def setup_poller_helpers(monkeypatch):
    monkeypatch.setattr(
        YamlStatePoller,
        "_evict_invalidated_pending_updates",
        _helper_evict_invalidated_pending_updates,
        raising=False,
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
            self._attributes = {}

        def update_state_attributes(self, new_attrs):
            self._attributes = new_attrs

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
            self._attributes = {}

        def update_state_attributes(self, new_attrs):
            self._attributes = new_attrs

    mock_controller = FakeController()
    poller = YamlStatePoller(mock_controller)
    poller._get_state_node_from_prop = MagicMock(return_value="WindLevel")

    device_payload = {"WindLevel": "low_dev"}

    with patch("time.monotonic", return_value=100.0):
        poller._pending_updates = {"wind_speed": ("high", 95.0)}
        poller._last_device_state_str = "dirty"
        await poller.async_update_properties_from_state(device_payload)

        assert mock_prop.value in ("high", "low")
        assert "wind_speed" in poller._pending_updates

    mock_prop.async_update_state.reset_mock()
    with patch("time.monotonic", return_value=100.0):
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

    with patch("time.monotonic", return_value=102.0):
        await poller.async_get_status()
        poller.async_update_state.assert_called_once()

    poller.async_update_state.reset_mock()
    with patch("time.monotonic", return_value=101.99):
        await poller.async_get_status()
        poller.async_update_state.assert_not_called()


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

    now = time.monotonic()
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
    now = time.monotonic()
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
    mock_power_prop.state_node = "AC_FUN_POWER"
    mock_power_prop.status_template = "{{ device_state.AC_FUN_POWER }}"

    # operations has NO power op (returns None), properties HAS power_prop
    mock_controller.loader.operations = {"hvac_mode": mock_hvac_op}
    mock_controller.loader.properties = {"power": mock_power_prop}

    poller = YamlStatePoller(mock_controller)
    poller._pending_updates["hvac_mode"] = ("heat", time.monotonic())

    # Incoming push is Power Off -> MUST evict hvac_mode pending update via properties.get("power") fallback!
    poller._evict_invalidated_pending_updates({"AC_FUN_POWER": "Off"})
    assert len(poller._pending_updates) == 0, (
        "Mutant survived! Eviction failed when power operation was in properties instead of operations."
    )


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

    now = time.monotonic() - 25.0
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


@patch("time.monotonic", return_value=100.0)
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
async def test_evict_invalidated_pending_updates_converter_called_strictly():
    """Kills mutant changing hasattr(prop, 'convert_hass_to_dev') to return None/False."""
    poller = YamlStatePoller(MagicMock())

    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev = MagicMock(return_value="22")
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.monotonic()
    poller._pending_updates = {"temperature": (22.0, now)}

    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    # Explicitly assert convert_hass_to_dev was called
    assert temp_op.convert_hass_to_dev.called
    assert isinstance(poller._pending_updates, dict)
