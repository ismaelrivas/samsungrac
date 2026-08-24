from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.helpers.template import Template
from homeassistant.helpers.update_coordinator import UpdateFailed

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
        self.__dict__.update(kwargs)


@pytest.mark.asyncio
async def test_mutant_deepcopy_async_get_status():
    """KILLS: copy.copy vs copy.deepcopy mutants in async_get_status & async_merge_device_state."""
    poller = YamlStatePoller(MagicMock())
    poller._last_state_fetch_time = time.time()

    # 1. Test async_get_status deepcopy
    nested_state = {"nested": {"k": "safe"}}
    poller.controller.loader.state_getter = NakedObj(value=nested_state)
    poller._cached_device_state = nested_state

    res = await poller.async_get_status()
    # Mutate the result. If deepcopy was mutated to copy.copy, the inner dict gets infected.
    res["nested"]["k"] = "hacked"
    assert poller.controller.loader.state_getter.value["nested"]["k"] == "safe", (
        "Deepcopy mutated to copy!"
    )

    # 2. Test async_merge_device_state deepcopy
    poller._pure_network_state = {"nested_pure": {"k": "safe"}}
    poller.async_update_properties_from_state = AsyncMock()
    await poller.async_merge_device_state({"new": "data"})
    poller.controller.loader.state_getter.value["nested_pure"]["k"] = "hacked"
    assert poller._pure_network_state["nested_pure"]["k"] == "safe", (
        "Merge deepcopy mutated!"
    )


@pytest.mark.asyncio
async def test_mutant_async_update_state_available_consecutive():
    """KILLS: mutants in `if getattr(...) and errors <= 2 and cached:` (lines 348-350) and `reason.split`."""
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

    # Setup for successful flow
    poller.controller.loader.state_getter = NakedObj(value={"state": "ok"})
    poller.async_update_properties_from_state = AsyncMock(
        return_value={"other_prop": "v2"}
    )
    poller.register_pending_update = MagicMock()

    # KILLS: `if op_id == property_name or self._get_hass_attr_for_op_id(op_id) == property_name:` mutated to `and`
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

    # 2. If the mutant changes `{}` to `None`, this update step will throw an AttributeError: 'NoneType' object has no attribute 'update'
    await poller.async_merge_device_state({"new": "update"})

    # 3. Assert the dictionary was correctly initialized and updated
    assert isinstance(poller._pure_network_state, dict)
    assert poller._pure_network_state["new"] == "update"


@pytest.mark.asyncio
async def test_mutant_predict_action_removals():
    """KILLS: removal of _set_prop_value and _inject_value_into_state calls in async_predict_and_correct_state."""
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
    """KILLS: parsed.get("json", parsed) mutated to parsed.get(None, parsed) in _inject_value_into_state."""
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
