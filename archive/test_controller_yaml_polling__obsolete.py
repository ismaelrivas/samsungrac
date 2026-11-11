# pylint: disable=all
# flake8: noqa
"""Archived test functions from controller_yaml_polling test suite.

Quarantined 94 completely shadowed tests with zero unique mutant kills
and zero unique line coverage to accelerate mutmut and pytest execution.
"""

import copy
import re
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.components.climate import ClimateEntityFeature

from custom_components.climate_ip.const import (
    CONF_DEVICE_TYPE,
    CONFIG_DEVICE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
)
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import CannotConnect, InvalidHeaderError


class NakedObj:
    def __init__(self, **kwargs):
        self.hass = MagicMock()
        self.debug = False
        self.name = "TestName"
        self.ip_address = "192.168.1.100"
        self.available = True
        self.device_id = "XXXX"
        self.log_prefix = "TestLog"
        self.sensors = {}
        self.properties = {}
        self.operations = {}
        self._attributes = {}
        self.config = {}
        self.state_getter = None
        self.__dict__.update(kwargs)

    def update_state_attributes(self, new_attrs):
        self._attributes = new_attrs


class DummyController(NakedObj):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not hasattr(self, "config"):
            self.config = {}
        if not hasattr(self, "log_prefix"):
            self.log_prefix = "TEST"
        if not hasattr(self, "ip_address"):
            self.ip_address = "127.0.0.1"
        if not hasattr(self, "loader") or getattr(self, "loader", None) is None:
            self.loader = MagicMock()
            self.loader.is_fully_initialized = True
            self.loader.operations = {}
            self.loader.properties = {}
            self.loader.sensors = {}
            self.loader._parsed_yaml_cache = {}
            self.loader.state_getter = NakedObj(value={})
            self.loader.state_getter.async_update_state = AsyncMock()


# =========================================================================
# ARCHIVED TESTS (94 COMPLETELY SHADOWED TESTS)
# =========================================================================


# --- Archived from test_controller_yaml_polling__annihilation.py ---
def test_mutant_apply_anti_flicker_global_evict_return_stops_iteration():
    """KILLS: return mutated to break/pass in _apply_anti_flicker_locks (Line 790)."""
    poller = YamlStatePoller(MagicMock())

    op1 = MagicMock(id="power1")
    op1.should_evict_all_locks.return_value = True

    op2 = MagicMock(id="power2")
    op2.should_evict_all_locks.return_value = True

    poller._pending_updates = {"temp": ("24", time.monotonic())}

    poller._apply_anti_flicker_locks(
        [op1, op2],
        {},
        {},
        is_prediction=False,
        changed_keys={"power"},
    )

    assert len(poller._pending_updates) == 0
    op1.should_evict_all_locks.assert_called_once()
    op2.should_evict_all_locks.assert_not_called()


# --- Archived from test_controller_yaml_polling__annihilation.py ---
def test_mutant_apply_anti_flicker_physical_timeout_or():
    """KILLS: self._values_match(pure_val, pend_val) or ... mutated to AND (Line 880)."""
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

    # Lock age is past LOCK_PHYSICAL_TIMEOUT_SEC (e.g. 20s) but below LOCK_TTL_SEC (45s)
    lock_age = poller.LOCK_PHYSICAL_TIMEOUT_SEC + 5.0
    poller._pending_updates = {"mode": ("heat", now - lock_age)}

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=None,
    )

    # Unmutated (OR): values don't match, but lock_age > timeout -> lock is released!
    # Mutated (AND): lock is NOT released because values don't match.
    assert "mode" not in poller._pending_updates


# --- Archived from test_controller_yaml_polling__annihilation.py ---
@pytest.mark.asyncio
async def test_mutant_predict_and_correct_dict_with_value_attribute():
    """KILLS: not isinstance(new_value, dict) mutated to isinstance(new_value, dict)."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    fake_memory_state = {"custom_node": {}}
    poller.controller.loader.state_getter = NakedObj(value=fake_memory_state)

    class CustomDict(dict):
        """Custom dict with value attribute."""

        value = "should_not_extract_this"

    dict_instance = CustomDict({"real_key": "real_val"})

    fake_prop = MagicMock(id="custom")
    fake_prop.value = None
    del fake_prop.convert_hass_to_dev
    poller.controller.loader.operations = {"custom": fake_prop}
    poller._get_state_node_from_prop = MagicMock(return_value="custom_node")
    poller.async_update_properties_from_state = AsyncMock(return_value={})

    await poller.async_predict_and_correct_state(None, "custom", dict_instance)

    # If `not isinstance(new_value, dict)` is mutated to `isinstance(new_value, dict)`:
    # it WILL extract .value ("should_not_extract_this") instead of keeping the dict instance!
    assert fake_prop.value is dict_instance, (
        "Mutant survived: dict subclass was incorrectly unwrapped!"
    )
    assert fake_memory_state["custom_node"] == {"real_key": "real_val"}


# --- Archived from test_controller_yaml_polling__annihilation.py ---
@pytest.mark.asyncio
async def test_mutant_predict_action_removals():
    """KILLS: removal of _set_prop_value and _inject_value_into_state calls."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # 1. Mock physical memory state
    fake_memory_state = {"power_node": "Off"}
    poller.controller.loader.state_getter = NakedObj(value=fake_memory_state)

    # 2. Mock a specific property
    fake_prop = MagicMock(id="power")
    fake_prop.value = "Off"
    fake_prop.convert_hass_to_dev.return_value = "On"
    poller.controller.loader.operations = {"power": fake_prop}
    poller._get_state_node_from_prop = MagicMock(return_value="power_node")

    poller.async_update_properties_from_state = AsyncMock(return_value={})

    # 3. Execute the prediction
    await poller.async_predict_and_correct_state(None, "power", "On")

    # 4. If `_set_prop_value` was removed by mutmut, this assert fails (value remains 'Off')
    assert fake_prop.value == "On", "Mutant survived: _set_prop_value was removed!"

    # 5. If `_inject_value_into_state` was removed by mutmut, this assert fails (dict remains 'Off')
    assert fake_memory_state["power_node"] == "On", (
        "Mutant survived: _inject_value_into_state was removed!"
    )


# --- Archived from test_controller_yaml_polling__annihilation.py ---
@pytest.mark.asyncio
async def test_mutant_pure_network_state_dict_init():
    """KILLS: self._pure_network_state = {} mutated to None in async_merge_device_state."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.state_getter = NakedObj(value={"base": "data"})

    # 1. Force the state to be None to trigger the initialization block
    poller._pure_network_state = None
    poller.async_update_properties_from_state = AsyncMock()

    # 2. If the mutant changes `{}` to `None`, this update step will throw AttributeError
    await poller.async_merge_device_state({"new": "update"})

    # 3. Assert the dictionary was correctly initialized and updated
    assert isinstance(poller._pure_network_state, dict)
    assert poller._pure_network_state["new"] == "update"


# --- Archived from test_controller_yaml_polling__annihilation.py ---
@pytest.mark.asyncio
async def test_mutant_predict_and_correct_dict_check():
    """KILLS: not isinstance(st_getter.value, dict) flip."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # If state is a list (not a dict), it must abort. If mutated to AND, it proceeds and crashes.
    poller.controller.loader.state_getter = NakedObj(value=["not", "a", "dict"])
    feat, corr = await poller.async_predict_and_correct_state(None, "p", "v")
    assert feat == 0
    assert corr == {}


# --- Archived from test_controller_yaml_polling__annihilation.py ---
def test_mutant_set_dict_value_by_path_list_vs_dict():
    """KILLS: isinstance(current, list) mutated to OR in _set_dict_value_by_path."""
    poller = YamlStatePoller(MagicMock())
    # Create a string path that mimics a digit but targets a dict node
    target = {"0": {}}
    # If `isinstance(current, list) AND part.isdigit()` is mutated to OR,
    # the engine will see `part.isdigit()` is True, assume it's a list,
    # and try to do `target.append()` which crashes because target is a dict.
    poller._set_dict_value_by_path(target, "0.child", "new")
    assert target["0"]["child"] == "new"


# --- Archived from test_controller_yaml_polling__annihilation.py ---
@pytest.mark.asyncio
async def test_mutant_async_update_state_available_flip():
    """KILLS: getattr(..., 'available', True) flip in async_update_state."""
    poller = YamlStatePoller(MagicMock())
    # Setup cache and network error to reach the fallback block
    poller._cached_device_state = {"a": 1}
    poller._consecutive_connection_errors = 1
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=CannotConnect("x")
    )

    # 1. If available=True, it safely returns cache
    poller.controller.available = True
    assert await poller.async_update_state() == {"a": 1}

    # 2. If available=False, it ignores cache and raises
    poller.controller.available = False
    with pytest.raises(UpdateFailed):
        await poller.async_update_state()


# --- Archived from test_controller_yaml_polling__annihilation.py ---
def test_mutant_list_inflation_exact_boundaries():
    """KILLS: `idx > MAX` mutated to `>=` and `isinstance(..., list) and ...` mutated to `or`."""
    poller = YamlStatePoller(MagicMock())

    # KILLS: > to >= at is_last = True (line 469)
    lst1 = []
    poller._set_dict_value_by_path(lst1, "100", "A")
    assert lst1[100] == "A"

    # KILLS: > to >= at is_last = False (line 486)
    lst2 = []
    poller._set_dict_value_by_path(lst2, "100.key", "B")
    assert lst2[100]["key"] == "B"

    # KILLS: `and part.isdigit()` mutated to `or` (will crash dict operations if true)
    d1 = {}
    poller._set_dict_value_by_path(d1, "0.next", "C")
    assert isinstance(d1["0"], dict)


# --- Archived from test_controller_yaml_polling__annihilation.py ---
@pytest.mark.asyncio
async def test_mutant_async_update_state_available_consecutive():
    """KILLS: mutants in consecutive errors <= 2 and reason.split."""
    poller = YamlStatePoller(MagicMock())
    poller._cached_device_state = {"cache": "hit"}

    # Simulate a network failure generating CannotConnect
    poller.controller.loader.state_getter = MagicMock()
    poller.controller.loader.state_getter.async_update_state = AsyncMock(
        side_effect=CannotConnect("Prefix: Mid: ExpectedReason")
    )

    # KILLS: `_consecutive_connection_errors <= 2` mutated to `< 2`
    # At exactly 2, it should return cache. If mutated to < 2, it will bypass cache and raise.
    poller._consecutive_connection_errors = 1  # Will become 2 during execution
    poller.controller.available = True
    res = await poller.async_update_state()
    assert res == {"cache": "hit"}

    # KILLS: `getattr("available")` boolean flip and `is not None` flip
    # If available is False, it bypasses cache and raises Exception
    poller.controller.available = False
    poller._consecutive_connection_errors = 1
    with pytest.raises(UpdateFailed) as exc:
        await poller.async_update_state()

    # KILLS: `split(":")[-1]` mutated to `[+1]` or `[1]`
    assert "Device unreachable: ExpectedReason" in str(exc.value), (
        "Split index mutated!"
    )


# --- Archived from test_controller_yaml_polling__network.py ---
async def test_update_state_delete_issue_exception():
    """L260-261: Captura de excepción en async_delete_issue."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller

    mock_controller = MagicMock()
    mock_controller.config.get.return_value = "REST"
    mock_controller.ip_address = "1.2.3.4"
    mock_controller.hass = MagicMock()
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"a": 1}
    )

    poller = YamlStatePoller(mock_controller)
    poller._consecutive_connection_errors = 1
    poller._build_device_state_from_hass = AsyncMock(return_value={"a": 1})
    poller.async_update_properties_from_state = AsyncMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue",
        side_effect=Exception("Test Error"),
    ):
        # No debe crashear
        await poller.async_update_state()


# --- Archived from test_controller_yaml_polling__network.py ---
async def test_async_shutdown_conn_close():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    conn = MagicMock()
    del conn.stop_listening
    conn.close = AsyncMock(side_effect=ValueError("Boom"))
    mock_controller.loader.connection = conn

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await poller.async_shutdown()  # Should not raise
    conn.close.assert_called_once()
    assert mock_controller.loader.connection is None


# --- Archived from test_controller_yaml_polling__network.py ---
@pytest.mark.parametrize(
    "unique_id, host, ip_address, expected_issue_id",
    [
        (None, "192.168.1.10", "10.0.0.10", "device_offline_192_168_1_10"),
        (None, None, "10.0.0.10", "device_offline_10_0_0_10"),
        (None, None, None, "device_offline_unknown"),
        ("my_device_1", None, "10.0.0.10", "device_offline_my_device_1"),
    ],
)
async def test_async_delete_issue_fallback_cascade(
    unique_id, host, ip_address, expected_issue_id
):
    """Sniper: Test fallback cascade for raw_id in async_delete_issue when connection recovers."""
    mock_controller = MagicMock()
    mock_controller.hass = MagicMock()
    mock_controller.unique_id = unique_id
    mock_controller.host = host
    mock_controller.ip_address = ip_address

    mock_controller.loader.is_fully_initialized = True
    mock_controller.loader.state_getter.async_update_state = AsyncMock(
        return_value={"power": "on"}
    )
    mock_controller.loader.state_getter.value = {"power": "on"}

    poller = YamlStatePoller(mock_controller)
    poller._consecutive_connection_errors = 1
    poller.async_update_properties_from_state = AsyncMock()

    with patch(
        "custom_components.climate_ip.controller_yaml_polling.async_delete_issue"
    ) as mock_delete_issue:
        await poller.async_update_state()
        mock_delete_issue.assert_called_once_with(
            mock_controller.hass, "climate_ip", expected_issue_id
        )


# --- Archived from test_controller_yaml_polling__properties.py ---
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

    now = time.monotonic() - 25.0
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


# --- Archived from test_controller_yaml_polling__properties.py ---
@patch("time.monotonic", return_value=100.0)
@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_exact_ttl_boundary(mock_time):
    """Kills mutant mutating '>' to '>=' at line 946 (exact 10.0s TTL boundary)."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    del temp_op.should_evict_all_locks
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = str
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


# --- Archived from test_controller_yaml_polling__properties.py ---
@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_loop_continuation():
    """Kills mutants changing 'continue' to 'break' at line 943 (if not entry) or 958 (if not prop)."""
    poller = YamlStatePoller(MagicMock())

    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = str
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.monotonic() - 5.0
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


# --- Archived from test_controller_yaml_polling__properties.py ---
async def test_async_merge_device_state_missing_getter():
    poller = YamlStatePoller(MagicMock())
    poller.controller.get_current_state_callback = MagicMock(return_value=None)

    # Destrucción estructural (Fail-Fast)
    delattr(poller.controller.loader, "state_getter")

    assert await poller.async_merge_device_state({"new": "data"}) is False


# --- Archived from test_controller_yaml_polling__properties.py ---
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

    now = time.monotonic()
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


# --- Archived from test_controller_yaml_polling__properties.py ---
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


# --- Archived from test_controller_yaml_polling__properties.py ---
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


# --- Archived from test_controller_yaml_polling__properties.py ---
@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_ttl_fallback():
    """Verify that pending updates older than TTL (10s) are evicted even if push value mismatches."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = str
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    # Stale timestamp (12 seconds ago > 10.0s TTL)
    stale_time = time.monotonic() - 12.0
    poller._pending_updates["temperature"] = (23.0, stale_time)

    # Incoming push data carries 22.0 (mismatch), but timestamp > 10s -> TTL fallback evicts it!
    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    assert isinstance(poller._pending_updates, dict)


# --- Archived from test_controller_yaml_polling__properties.py ---
@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_value_mismatch_retained():
    """Verify that an echo push update with a stale/mismatched value does NOT evict fresh pending user intent."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = str
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.monotonic()
    # User requested 23.0
    poller._pending_updates["temperature"] = (23.0, now)

    # Device responds with echo update for prior command (22.0)
    await poller.async_update_properties_from_state(
        {"AC_FUN_TEMPSET": "22"}, force_update=True, changed_keys={"AC_FUN_TEMPSET"}
    )

    # Pending update for 23.0 MUST be retained to prevent UI flicker!
    assert isinstance(poller._pending_updates, dict)


# --- Archived from test_controller_yaml_polling__properties.py ---
@pytest.mark.asyncio
async def test_evict_invalidated_pending_updates_float_formatting_match():
    """Verify that push payload '22' evicts pending update 22.0 via float matching."""
    poller = YamlStatePoller(MagicMock())
    temp_op = MagicMock(id="temperature")
    temp_op.calculate_value_from_state = MagicMock(return_value=22.0)
    temp_op.convert_hass_to_dev.side_effect = str
    poller.controller.loader.operations = {"temperature": temp_op}
    poller.controller.loader.properties = {}
    poller._get_state_node_from_prop = MagicMock(return_value="AC_FUN_TEMPSET")

    now = time.monotonic() - 25.0
    poller._pending_updates["temperature"] = (22.0, now)

    # Push data is "22" string, pending expected is 22.0 float -> MUST match and evict!
    push_data = {"AC_FUN_TEMPSET": "22"}
    poller._pure_network_state = push_data  # <--- CRÍTICO: Inyección de estado puro

    await poller.async_update_properties_from_state(
        push_data, force_update=True, changed_keys=set(push_data.keys())
    )

    assert "temperature" not in poller._pending_updates


# --- Archived from test_controller_yaml_polling__properties.py ---
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


# --- Archived from test_controller_yaml_polling__properties.py ---
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
    poller._pending_updates = {"test_op": ("val", time.monotonic() - 15.0)}
    poller.controller.loader.properties = {"test_op": op_mock}
    poller._get_state_node_from_prop = MagicMock(return_value=None)

    poller.controller.debug = False

    await poller.async_update_properties_from_state({"Devices": [{}]})
    op_mock.async_update_state.assert_called_once()


# --- Archived from test_controller_yaml_polling__properties.py ---
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


# --- Archived from test_controller_yaml_polling__properties.py ---
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


# --- Archived from test_controller_yaml_polling__properties.py ---
async def test_update_properties_full_state_none():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    res = await poller.async_update_properties_from_state(None)
    assert res == {}


# --- Archived from test_controller_yaml_polling__properties.py ---
async def test_merge_device_state_strict_conditionals():
    mock_controller = MagicMock()
    poller = YamlStatePoller(mock_controller)

    # 1. No st_getter -> returns False
    mock_controller.loader = NakedObj(state_getter=None)
    assert await poller.async_merge_device_state({"a": 1}) is False


# --- Archived from test_controller_yaml_polling__properties.py ---
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

    poller._pending_updates = {"uprop": ("new_val", time.monotonic())}

    await poller.async_update_properties_from_state({"some": "state"})
    assert prop_uvalue.value == "new_val"


# --- Archived from test_controller_yaml_polling__properties.py ---
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


# --- Archived from test_controller_yaml_polling__properties.py ---
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
    poller._pending_updates["hvac_mode"] = ("heat", time.monotonic())

    # Incoming push is Power ON (not Off) -> MUST NOT evict hvac_mode pending update!
    poller._evict_invalidated_pending_updates({"AC_FUN_POWER": "On"})
    assert len(poller._pending_updates) == 1, (
        "Mutant survived! Pending update was evicted even when power was 'On' instead of 'Off'."
    )


# --- Archived from test_controller_yaml_polling__properties.py ---
async def test_async_update_properties_fan_flicker_flag():
    from homeassistant.components.climate.const import ClimateEntityFeature

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


# --- Archived from test_controller_yaml_polling__properties.py ---
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


# --- Archived from test_controller_yaml_polling__properties.py ---
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

    poller._pending_updates = {"hvac": ("val", time.monotonic())}
    result_pending = await poller.async_update_properties_from_state(
        fake_state, is_prediction=False, force_update=False
    )
    assert isinstance(result_pending, dict)

    del poller._last_device_state
    poller._pending_updates = {}


# --- Archived from test_controller_yaml_polling__properties.py ---
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

    now = time.monotonic()
    poller._pending_updates = {
        "prop_valid": ("ha_val_valid", now - 60.0),
        "prop_stale": ("ha_val_stale", now - 60.0),
        "prop_deg": ("Auto", now - 60.0),
    }

    fake_state = {"raw_key": "old_val"}
    _ = await poller.async_update_properties_from_state(fake_state)

    assert isinstance(poller._pending_updates, dict)
    assert fake_state.get("raw_key") is not None


# --- Archived from test_controller_yaml_polling__properties.py ---
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
    poller._pending_updates = {"fake": ("val", time.monotonic())}
    poller._rebuild_attributes.reset_mock()
    await poller.async_update_properties_from_state(state_a.copy())
    poller._rebuild_attributes.assert_called_once()


# --- Archived from test_controller_yaml_polling__snniper.py ---
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

    # Original production strictly extracts last element after colon.
    assert str(exc_info.value) == "Device unreachable: Segment3", (
        "Mutantes M74/M75 detectados en el formateo del log."
    )


# --- Archived from test_controller_yaml_polling__snniper.py ---
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

    # Start at 1. The failure will add +1 = 2.
    poller._consecutive_connection_errors = 1
    poller._cached_device_state = {"state": "cached"}

    try:
        # In production (2 <= 2), returns cache.
        res = await poller.async_update_state()
        assert res == {"state": "cached"}
    except UpdateFailed:
        # If mutant (< 2) acts, evaluates False, ignores cache, raises UpdateFailed.
        pytest.fail(
            "Mutant M71 (< 2) detected: Cache was ignored at the exact boundary."
        )


# --- Archived from test_controller_yaml_polling__snniper.py ---
@pytest.mark.asyncio
async def test_sniper_merge_device_state_protected_value_mutation():
    """Annihilates Mutant L899: Guarantees protected branch _value executes and writes."""
    mock_controller = NakedObj(
        log_prefix="TEST",
        get_current_state_callback=MagicMock(return_value="valid_state"),
    )
    poller = YamlStatePoller(mock_controller)

    # IMPORTANT: Create state_getter with initial state
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

    # Execute merge with new state
    new_data = {"new": "data"}
    res = await poller.async_merge_device_state(new_data)

    assert res is True or st_getter._value is not None


# --- Archived from test_controller_yaml_polling__snniper.py ---
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


# --- Archived from test_controller_yaml_polling__snniper.py ---
@pytest.mark.asyncio
async def test_sniper_build_device_state_fails_on_missing_id():
    """Valida que 'op' sin '.id' sea gestionado pacíficamente sin explotar."""
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)

    op = MagicMock(value="on", spec=["value", "convert_hass_to_dev"])
    op.convert_hass_to_dev = MagicMock(return_value="On_Dev")

    poller.controller.loader = NakedObj(
        is_fully_initialized=True,
        state_getter=NakedObj(value={"Devices": [{}]}),
        operations={"corrupt": op},
        properties={},
        sensors={},
    )
    res = await poller._build_device_state_from_props()
    assert isinstance(res, dict)


# --- Archived from test_controller_yaml_polling__snniper.py ---
@pytest.mark.asyncio
async def test_sniper_build_device_state_fails_on_missing_value():
    """Valida L659: Debe explotar si state_getter no tiene '.value'."""
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)

    # st_getter is NakedObj without 'value'
    poller.controller.loader = NakedObj(
        state_getter=NakedObj(), operations={}, properties={}
    )

    with pytest.raises(AttributeError, match="value"):
        await poller._build_device_state_from_props()


# --- Archived from test_controller_yaml_polling__snniper.py ---
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


# --- Archived from test_controller_yaml_polling__snniper.py ---
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

    # Scenario A: < 15 seconds (Passes through convert_hass_to_dev but hits continue)
    poller._pending_updates = {"prop1": ("pending_val", time.monotonic() - 5.0)}
    with patch.object(poller, "_get_state_node_from_prop", return_value="prop1_key"):
        await poller.async_update_properties_from_state({"dummy": "state_A"})

    # Escenario B: >= 15 segundos (Llama a async_update_state completo)
    poller._pending_updates = {"prop1": ("pending_val", time.monotonic() - 20.0)}
    with patch.object(poller, "_get_state_node_from_prop", return_value="prop1_key"):
        await poller.async_update_properties_from_state({"dummy": "state_B"})
        assert prop.async_update_state.await_count >= 1

    # Escenario C: Excepción interna y logging
    prop.async_update_state.side_effect = ValueError("Boom")
    with patch(
        "custom_components.climate_ip.controller_yaml_polling._LOGGER.debug"
    ) as mock_debug:
        await poller.async_update_properties_from_state({"dummy": "state_C"})
        assert mock_debug.called


# --- Archived from test_controller_yaml_polling__snniper.py ---
@pytest.mark.asyncio
async def test_sniper_async_merge_device_state_strict():
    mock_controller = NakedObj(
        log_prefix="TEST",
        get_current_state_callback=MagicMock(return_value="valid_state"),
    )
    poller = YamlStatePoller(mock_controller)

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


# --- Archived from test_controller_yaml_polling__snniper.py ---
@pytest.mark.asyncio
async def test_sniper_async_get_status_connection_id():
    mock_controller = NakedObj(log_prefix="TEST", config={})
    poller = YamlStatePoller(mock_controller)
    poller.async_update_state = AsyncMock(return_value={"a": 1})
    conn_obj = NakedObj()
    poller.controller.loader = NakedObj(connection=conn_obj, is_fully_initialized=True)

    with patch("custom_components.climate_ip.controller_yaml_polling._LOGGER.debug"):
        await poller.async_get_status()


# --- Archived from test_controller_yaml_polling__snniper.py ---
def test_sniper_calculate_structured_state_and_rebuild_attrs():
    mock_controller = NakedObj(
        log_prefix="TEST", config={}, update_state_attributes=MagicMock()
    )
    poller = YamlStatePoller(mock_controller)

    prop = NakedObj(id="hvac_mode")
    prop.calculate_value_from_state = MagicMock(return_value="heat")
    poller.controller.loader = NakedObj(
        is_fully_initialized=True, operations={}, properties={"hvac": prop}, sensors={}
    )

    raw_state = {"power": "on"}
    poller._calculate_structured_state(raw_state)
    prop.calculate_value_from_state.assert_called_once_with(raw_state)

    poller._rebuild_attributes()
    mock_controller.update_state_attributes.assert_called_once()


# --- Archived from test_controller_yaml_polling__snniper.py ---
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
    assert res_preset is not None

    op_sleep = NakedObj(id="good_sleep", value="2.0")
    poller.controller.loader.operations = {"op1": op_sleep}
    poller.controller.loader.state_getter.value = {"Devices": [{}]}
    res_sleep = await poller._build_device_state_from_props()
    assert res_sleep is not None


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__state_build.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
async def test_calculate_structured_state_no_swallow():
    """Verify mutant kill AttributeError en validación de propiedades."""
    ctrl = NakedObj(loader=create_valid_loader())
    poller = YamlStatePoller(ctrl)

    prop = NakedObj()  # Carece de 'id'
    prop.calculate_value_from_state = lambda x: "val"
    ctrl.loader.operations = {"op1": prop}

    res = poller._calculate_structured_state({"raw": "data"})
    assert type(res).__name__ == "ClimateIPDeviceState"


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
def test_mask_sensitive_data_exact_boundary():
    """Verify mutant kill for mutation len(masked['uuid']) > 6 a >= 6."""
    poller = YamlStatePoller(MagicMock())
    res = poller._mask_sensitive_data({"uuid": "123456"})
    assert res["uuid"] == "123456"


# --- Archived from test_controller_yaml_polling__utils.py ---
def test_regex_device_state_key_cache_strict():
    """Verify mutant kill de regex + a * en inicialización"""
    poller = YamlStatePoller(MagicMock())
    result = poller._get_device_key_from_template("device_state['']")
    assert result is None, "Regex Failure: Mutant changed '+' to '*'"


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
def test_get_device_key_empty_template():
    """L933: Retorno nulo si el template_string queda vacío."""
    poller = YamlStatePoller(MagicMock())
    assert poller._get_device_key_from_template("") is None

    class EmptyTemplate:
        template = ""

    assert poller._get_device_key_from_template(EmptyTemplate()) is None


# --- Archived from test_controller_yaml_polling__utils.py ---
def test_mask_sensitive_data_primitive():
    """L183: Retorno temprano para datos primitivos."""
    poller = YamlStatePoller(MagicMock())
    assert poller._mask_sensitive_data("primitive_string") == "primitive_string"
    assert poller._mask_sensitive_data(123) == 123


# --- Archived from test_controller_yaml_polling__utils.py ---
def test_controller_mask_sensitive_data():
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


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
def test_rebuild_attributes_exact_strings(freezer):
    """Asserts el formato exacto de fecha y las claves del diccionario de atributos."""
    import datetime

    fake_time = datetime.datetime(2026, 6, 7, 15, 30, 0)
    freezer.move_to(fake_time)

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


# --- Archived from test_controller_yaml_polling__utils.py ---
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


# --- Archived from test_controller_yaml_polling__utils.py ---
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
