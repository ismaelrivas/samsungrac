# pylint: disable=protected-access,too-few-public-methods,too-many-instance-attributes
"""Tests dedicated to annihilating surviving and untested mutants in YamlStatePoller."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, call, patch

from homeassistant.helpers.template import Template
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.climate_ip.const import DEVICE_TYPE_MIM_H03
from custom_components.climate_ip.controller_yaml_polling import YamlStatePoller
from custom_components.climate_ip.exceptions import CannotConnect


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
        self.hass = MagicMock()
        self._attributes = {}
        self.__dict__.update(kwargs)

    def update_state_attributes(self, new_attrs):
        """Update simulated state attributes."""
        self._attributes = new_attrs


@pytest.mark.asyncio
async def test_mutant_deepcopy_async_get_status():
    """Verify shallow copy semantics in async_get_status & async_merge_device_state."""
    poller = YamlStatePoller(MagicMock())
    poller._last_state_fetch_time = time.monotonic()

    # 1. Test async_get_status shallow copy
    nested_state = {"nested": {"k": "safe"}}
    poller.controller.loader.state_getter = NakedObj(value=nested_state)
    poller._cached_device_state = nested_state

    res = await poller.async_get_status()
    # Shallow copy creates a distinct top-level dict reference
    assert res is not nested_state
    assert res == nested_state

    # 2. Test async_merge_device_state shallow copy
    poller._pure_network_state = {"nested_pure": {"k": "safe"}}
    poller.async_update_properties_from_state = AsyncMock()
    await poller.async_merge_device_state({"new": "data"})
    assert poller.controller.loader.state_getter.value is not poller._pure_network_state
    assert poller.controller.loader.state_getter.value["new"] == "data"


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


def test_mutant_discover_target_node_none_fallback():
    """KILLS: `next(..., None)` fallback removed in _discover_target_node."""
    poller = YamlStatePoller(MagicMock())
    devices = [{"id": "0", "Mode": "Cool"}, {"id": "1", "NoModeHere": "Yes"}]
    # None of these meet `id != "0" and "Mode" in d`. Should trigger `None` fallback safely.
    res = poller._discover_target_node(DEVICE_TYPE_MIM_H03, devices)
    assert res is None


@pytest.mark.asyncio
async def test_mutant_predict_and_correct_logic_flips():
    """KILLS: Boolean flips inside async_predict_and_correct_state."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # KILLS: `if not st_getter.value or not isinstance...` mutated to `and`
    poller.controller.loader.state_getter = NakedObj(value=None)
    feat, corr = await poller.async_predict_and_correct_state(None, "prop", "val")
    assert feat == 0
    assert corr == {}

    # Setup for successful flow
    poller.controller.loader.state_getter = NakedObj(value={"state": "ok"})
    poller.async_update_properties_from_state = AsyncMock(
        return_value={"other_prop": "v2"}
    )
    poller.register_pending_update = MagicMock()

    # KILLS: `if op_id == property_name or ...` mutated to `and`
    fake_op = MagicMock(id="not_the_prop")
    del fake_op.convert_hass_to_dev
    poller._get_state_node_from_prop = MagicMock(return_value="not_the_prop")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="target_prop")
    poller.controller.loader.operations = {"not_the_prop": fake_op}

    await poller.async_predict_and_correct_state(None, "target_prop", "val")

    # KILLS: `is_prediction=True` mutated to False
    poller.async_update_properties_from_state.assert_called_once_with(
        {"state": "ok", "not_the_prop": "val"}, is_prediction=True
    )

    # KILLS: `if k not in corrections and k != property_name:` mutated to `or` / `in`
    assert poller.register_pending_update.call_args_list == [
        call("target_prop", "val"),
        call("other_prop", "v2"),
    ]


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


def test_mutant_values_match_hasattr_dict_flip():
    """KILLS: not isinstance(val, dict) flip in _values_match."""
    # We pass a dict that HAS a "value" key.
    # The code: `if hasattr(val, "value") and not isinstance(val, dict): val = val.value`
    # It must NOT extract the value from the dict. It must compare the dicts.
    d1 = {"value": 1}
    d2 = {"value": 2}
    # If the mutant removes `not isinstance(..., dict)`, it will extract 1 and 2 and compare them.
    # We want to ensure it compares the dicts themselves.
    assert YamlStatePoller._values_match(d1, d1) is True
    assert YamlStatePoller._values_match(d1, d2) is False


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


def test_mutant_inject_value_connection_template_json_key():
    """KILLS: parsed.get("json", parsed) mutated to parsed.get(None, parsed)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}

    prop = MagicMock(id="good_sleep")
    del prop.convert_hass_to_dev
    prop.connection_template = Template(
        '{"json": {"options": ["Sleep_{{ value | int }}"]}}',
        hass=MagicMock(data={}),
    )
    poller._get_state_node_from_prop = MagicMock(return_value="Device.GoodSleep")

    poller._inject_value_into_state(prop, target_state, 5)

    # When unmutated: payload = {"options": ["Sleep_5"]}, dev_val becomes "Sleep_5"
    # When mutated with .get(None, parsed): payload remains {"json": {"options": ["Sleep_5"]}},
    # "options" not in payload, so dev_val remains 5 != "Sleep_5".
    assert target_state.get("Device", {}).get("GoodSleep") == "Sleep_5"


@pytest.mark.asyncio
async def test_mutant_predict_and_correct_enum_unwrapping():
    """KILLS: new_value is None and isinstance(new_value, dict) flips."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    fake_memory_state = {"mode_node": "cool"}
    poller.controller.loader.state_getter = NakedObj(value=fake_memory_state)

    class MockModeEnum:
        """Mock enum for test."""

        value = "heat"

    fake_prop = MagicMock(id="mode")
    fake_prop.value = "cool"
    del fake_prop.convert_hass_to_dev
    poller.controller.loader.operations = {"mode": fake_prop}
    poller._get_state_node_from_prop = MagicMock(return_value="mode_node")
    poller.async_update_properties_from_state = AsyncMock(return_value={})

    enum_val = MockModeEnum()
    await poller.async_predict_and_correct_state(None, "mode", enum_val)

    # KILLS:
    # 1. new_value is not None -> new_value is None
    # 2. not isinstance(new_value, dict) -> isinstance(new_value, dict)
    assert fake_prop.value == "heat", (
        "Mutant survived: Enum was not unwrapped to .value!"
    )
    assert fake_memory_state["mode_node"] == "heat"
    assert not hasattr(fake_prop.value, "value"), (
        "Property value should be primitive unwrapped string!"
    )


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


def test_mutant_inject_value_rendered_not_string():
    """KILLS: if rendered and isinstance(rendered, str): mutated to `or` (M24)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}
    prop = MagicMock(id="test")
    del prop.convert_hass_to_dev
    prop.connection_template = Template("doesnt_matter", hass=MagicMock())
    poller._get_state_node_from_prop = MagicMock(return_value="Node")

    # If render_template returns bytes, isinstance(rendered, str) is False.
    # Unmutated: False. Mutated (or): True, proceeds to json_loads(bytes) which succeeds!
    # Result: mutated code modifies target_state, unmutated does not.
    with patch(
        "custom_components.climate_ip.controller_yaml_polling.render_template",
        return_value=b'{"json": {"options": ["Mutated!"]}}',
    ):
        poller._inject_value_into_state(prop, target_state, 5)

    # Unmutated should use the default dev_val (5).
    # Mutated will parse the bytes and use "Mutated!".
    assert target_state.get("Node") == 5, "Mutant survived: parsed bytes payload!"


def test_mutant_inject_value_no_json_key():
    """KILLS: parsed.get("json", parsed) mutated to .get("json", None) (M29)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}
    prop = MagicMock(id="test")
    del prop.convert_hass_to_dev
    # The JSON string directly has "options", no "json" key.
    prop.connection_template = Template(
        '{"options": ["DirectVal"]}', hass=MagicMock(data={})
    )
    poller._get_state_node_from_prop = MagicMock(return_value="Node")

    poller._inject_value_into_state(prop, target_state, 5)

    # Unmutated: payload becomes {"options": ["DirectVal"]}, extracts "DirectVal".
    # Mutated: payload becomes None, fails isinstance(payload, dict), dev_val unchanged (5).
    assert target_state.get("Node") == "DirectVal", (
        "Mutant survived: parsed.get fell back to None!"
    )


def test_mutant_inject_value_options_not_list():
    """KILLS: isinstance(payload['options'], list) mutated to `or` (M34)."""
    poller = YamlStatePoller(MagicMock())
    target_state = {}
    prop = MagicMock(id="test")
    del prop.convert_hass_to_dev
    # "options" is a string, not a list!
    prop.connection_template = Template(
        '{"options": "StringVal"}', hass=MagicMock(data={})
    )
    poller._get_state_node_from_prop = MagicMock(return_value="Node")

    poller._inject_value_into_state(prop, target_state, 5)

    # Unmutated: isinstance(list) is False, block skipped.
    # Mutated: `or` makes it True, enters block, payload["options"][0] extracts "S"!
    assert target_state.get("Node") != "S", (
        "Mutant survived: options list check was bypassed!"
    )


def test_mutant_apply_anti_flicker_global_evict():
    """KILLS: global_evict = True mutated to False in _apply_anti_flicker_locks (Line 790)."""
    poller = YamlStatePoller(MagicMock())
    now = time.monotonic()

    # op_evict has should_evict_all_locks returning True
    op_evict = MagicMock(id="power")
    op_evict.should_evict_all_locks.return_value = True

    # op_target has a pending lock
    op_target = MagicMock(id="temperature")
    op_target.calculate_value_from_state.return_value = 24
    del op_target.should_evict_all_locks

    def get_state_node(op):
        if op.id == "power":
            return "power_node"
        return "temp_node"

    poller._get_state_node_from_prop = get_state_node

    all_props = [op_evict, op_target]
    device_to_process = {"temp_node": 24}
    pure_device_to_process = {"temp_node": 24}

    # Set pending update with age past LOCK_SHIELD_SEC (e.g. 5s)
    poller._pending_updates = {
        "temperature": (24, now - (poller.LOCK_SHIELD_SEC + 1.0))
    }

    # changed_keys does NOT include "temp_node", but global_evict is True
    changed_keys = {"power_node"}

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=changed_keys,
    )

    op_evict.should_evict_all_locks.assert_called_with(
        pure_device_to_process, changed_keys
    )

    # When unmutated: global_evict is True -> can_release is True -> lock is released
    # When mutated (global_evict = False): can_release is False -> lock remains in _pending_updates
    assert "temperature" not in poller._pending_updates


def test_mutant_apply_anti_flicker_hass_attr_mapping():
    """KILLS: if hass_attr != op_id mutated to == in _apply_anti_flicker_locks (Line 809)."""
    poller = YamlStatePoller(MagicMock())
    now = time.monotonic()

    # Create an operation where hass_attr differs from op.id
    op = MagicMock(id="target_temperature_op")
    del op.should_evict_all_locks
    del op.convert_hass_to_dev
    op.calculate_value_from_state.return_value = 22
    poller._get_state_node_from_prop = MagicMock(return_value="target_temp_node")
    poller._get_hass_attr_for_op_id = MagicMock(return_value="target_temperature")

    all_props = [op]
    device_to_process = {"target_temp_node": 20}
    pure_device_to_process = {"target_temp_node": 20}

    # The pending update is registered under the HA attribute name ("target_temperature")
    poller._pending_updates = {
        "target_temperature": (22, now - 1.0)
    }

    poller._apply_anti_flicker_locks(
        all_props,
        device_to_process,
        pure_device_to_process,
        is_prediction=False,
        changed_keys=None,
    )

    # Unmutated: props_by_id["target_temperature"] = op -> op found -> lock enforced on op
    # Mutated (if hass_attr == op_id): props_by_id["target_temperature"] not set -> not enforced
    assert device_to_process["target_temp_node"] == 22


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
    poller._pending_updates = {
        "mode": ("heat", now - lock_age)
    }

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


def test_mutant_predict_dependency_cascades_continue():
    """KILLS: continue mutated to break in _predict_dependency_cascades (Line 913)."""
    poller = YamlStatePoller(MagicMock())

    # op1 is invalid (is_valid returns False)
    op1 = MagicMock(id="op1_invalid")
    op1.is_valid.return_value = False
    del op1.get_valid_values

    # op2 is valid and needs cascade correction
    op2 = MagicMock(id="op2_valid")
    op2.is_valid.return_value = True
    del op2.get_valid_values
    op2.values = ["val_a", "val_b"]
    poller._get_prop_value = MagicMock(
        side_effect=lambda op: "invalid_val" if op.id == "op2_valid" else None
    )
    poller._get_state_node_from_prop = MagicMock(return_value="op2_node")

    poller.controller.loader.operations = {
        "op1": op1,
        "op2": op2,
    }

    corrections = poller._predict_dependency_cascades({})

    # Unmutated (continue): op1 skipped, op2 processed -> op2 corrected to "val_a"
    # Mutated (break): loop breaks at op1, op2 never processed -> corrections is empty
    assert corrections == {"op2_valid": "val_a"}


@pytest.mark.asyncio
async def test_mutant_async_merge_device_state_is_none():
    """KILLS: if getattr(..., '_pure_network_state', None) is None flip (Line 1071)."""
    poller = YamlStatePoller(MagicMock())
    poller.async_update_properties_from_state = AsyncMock()

    # Pre-existing state in _pure_network_state, while st_getter.value is None
    poller._pure_network_state = {"existing_key": "existing_value"}
    poller.controller.loader.state_getter = NakedObj(value=None)

    res = await poller.async_merge_device_state({"new_key": "new_value"})

    # Unmutated: _pure_network_state is not None, so line 1071 is skipped.
    # not self._pure_network_state is False.
    # update() is called with new_data -> returns True.
    # Mutated (is not None): line 1071 executes -> self._pure_network_state = {}
    # not self._pure_network_state is True -> st_getter.value is None -> returns False!
    assert res is True
    assert poller._pure_network_state == {
        "existing_key": "existing_value",
        "new_key": "new_value",
    }


@pytest.mark.asyncio
async def test_mutant_async_update_properties_st_getter_and_value():
    """KILLS: if st_getter and st_getter.value mutated to or (Line 962)."""
    poller = YamlStatePoller(MagicMock())
    poller.controller.loader.is_fully_initialized = True

    # st_getter exists (truthy object), but value is None
    poller.controller.loader.state_getter = NakedObj(value=None)

    poller._extract_device_nodes = MagicMock()

    # Call with full_device_state=None
    res = await poller.async_update_properties_from_state(full_device_state=None)

    # Unmutated: `st_getter and st_getter.value` is False -> returns {} without calling extract
    # Mutated (or): `st_getter or st_getter.value` is True -> calls _extract_device_nodes
    assert res == {}
    poller._extract_device_nodes.assert_not_called()


def test_untested_device_state_and_pure_network_state_properties():
    """Test full branch coverage for device_state and pure_network_state properties."""
    poller = YamlStatePoller(MagicMock())

    # --- Test device_state ---
    poller._last_device_state = None
    assert poller.device_state == {}

    poller._last_device_state = {"power": "on"}
    assert poller.device_state == {"power": "on"}

    # --- Test pure_network_state ---
    # 1. None state
    poller._pure_network_state = None
    assert poller.pure_network_state == {}

    # 2. Empty dict
    poller._pure_network_state = {}
    assert poller.pure_network_state == {}

    # 3. Non-dict type
    poller._pure_network_state = ["not", "a", "dict"]  # type: ignore[assignment]
    assert poller.pure_network_state == {}

    # 4. Standard dict without Devices key
    poller._pure_network_state = {"temp": 21, "mode": "cool"}
    assert poller.pure_network_state == {"temp": 21, "mode": "cool"}

    # 5. Devices key is a valid list of dicts (Samsung format unwrap)
    poller._pure_network_state = {
        "Devices": [{"id": "0", "power": "on"}, {"id": "1", "power": "off"}]
    }
    assert poller.pure_network_state == {"id": "0", "power": "on"}

    # 6. Devices key is empty list
    poller._pure_network_state = {"Devices": []}
    assert poller.pure_network_state == {"Devices": []}

    # 7. Devices key is not a list (e.g. dict or str)
    poller._pure_network_state = {"Devices": "invalid"}
    assert poller.pure_network_state == {"Devices": "invalid"}

    # 8. Devices list contains non-dict first element
    poller._pure_network_state = {"Devices": ["invalid_string"]}
    assert poller.pure_network_state == {"Devices": ["invalid_string"]}
