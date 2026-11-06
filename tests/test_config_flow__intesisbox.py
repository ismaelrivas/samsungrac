# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Test the Climate IP config flow for IntesisBox."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.climate_ip.config_flow import ClimateIpConfigFlow
from custom_components.climate_ip.const import (
    CONF_CONFIG_FILE,
    CONF_DEVICE_TYPE,
    CONF_POLL_INTERVAL,
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_TO_CONFIG_FILE,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_NAME, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow, FlowResultType


async def test_step_intesisbox_show_form_default_schema(hass: HomeAssistant) -> None:
    """Test async_step_intesisbox renders form with proper schema and defaults when user_input is None."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {CONF_IP_ADDRESS: "10.0.0.1", CONF_MAC: "001122334455"}

    result = await flow.async_step_intesisbox(user_input=None)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "intesisbox"
    assert result["errors"] == {}

    schema = result["data_schema"]
    ip_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_IP_ADDRESS
    )
    assert ip_key.default() == "10.0.0.1"

    mac_key = next(k for k in schema.schema if getattr(k, "schema", None) == CONF_MAC)
    assert mac_key.description == {"suggested_value": "001122334455"}

    poll_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_POLL_INTERVAL
    )
    assert poll_key.default() == 60


async def test_step_intesisbox_invalid_poll_interval(hass: HomeAssistant) -> None:
    """Test async_step_intesisbox error handling on invalid poll interval."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_intesisbox(
        {CONF_IP_ADDRESS: "192.168.1.50", CONF_POLL_INTERVAL: -1}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "intesisbox"
    assert result["errors"] == {CONF_POLL_INTERVAL: "invalid_poll_interval"}


async def test_step_intesisbox_connection_error(hass: HomeAssistant) -> None:
    """Test async_step_intesisbox handles socket connection failure."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    with patch("asyncio.open_connection", side_effect=OSError("Connection failed")):
        result = await flow.async_step_intesisbox(
            {CONF_IP_ADDRESS: "192.168.1.50", CONF_POLL_INTERVAL: 30}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "intesisbox"
    assert result["errors"] == {"base": "cannot_connect"}
    assert flow.flow_data[CONF_POLL_INTERVAL] == 30


async def test_step_intesisbox_mac_resolution_error(hass: HomeAssistant) -> None:
    """Test async_step_intesisbox handles MAC resolution error."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    mock_reader = AsyncMock()
    mock_reader.read.return_value = (
        b"ID:IS-IR-WMP-1,00:1D:C9:A2:C9:11,192.168.1.50,1.9,-44\r\n"
    )
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch.object(
            flow,
            "_async_resolve_mac_and_set_unique_id",
            return_value="cannot_resolve_mac",
        ):
            result = await flow.async_step_intesisbox({CONF_IP_ADDRESS: "192.168.1.50"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_resolve_mac"}


async def test_step_intesisbox_already_configured_abort(hass: HomeAssistant) -> None:
    """Test async_step_intesisbox aborts when unique id already configured."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    mock_reader = AsyncMock()
    mock_reader.read.return_value = (
        b"ID:IS-IR-WMP-1,001DC9A2C911,192.168.1.50,1.9,-44\r\n"
    )
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch.object(
            flow, "_async_resolve_mac_and_set_unique_id", return_value=None
        ):
            with patch.object(
                flow,
                "_abort_if_unique_id_configured",
                side_effect=AbortFlow("already_configured"),
            ) as mock_abort:
                with pytest.raises(AbortFlow) as exc_info:
                    await flow.async_step_intesisbox({CONF_IP_ADDRESS: "192.168.1.50"})
                assert exc_info.value.reason == "already_configured"
                mock_abort.assert_called_once()


async def test_step_intesisbox_success_full(hass: HomeAssistant) -> None:
    """Test full successful async_step_intesisbox flow with MAC normalized from ID response."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}

    # 1. Step user: select intesisbox
    user_res = await flow.async_step_user({CONF_DEVICE_TYPE: DEVICE_TYPE_INTESISBOX})
    assert user_res["type"] == FlowResultType.FORM
    assert user_res["step_id"] == "intesisbox"

    mock_reader = AsyncMock()
    mock_reader.read.return_value = (
        b"ID:IS-IR-WMP-1,00:1D:C9:A2:C9:11,192.168.1.50,1.9,-44\r\n"
    )
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with (
        patch(
            "asyncio.open_connection", return_value=(mock_reader, mock_writer)
        ) as mock_open,
        patch.object(
            flow, "_async_resolve_mac_and_set_unique_id", return_value=None
        ) as mock_resolve,
    ):
        result = await flow.async_step_intesisbox(
            {CONF_IP_ADDRESS: "192.168.1.50", CONF_POLL_INTERVAL: 45}
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "IntesisBox (192.168.1.50)"
    data = result["data"]
    assert data[CONF_NAME] == "IntesisBox (192.168.1.50)"
    assert data[CONF_DEVICE_TYPE] == DEVICE_TYPE_INTESISBOX
    assert data[CONF_CONFIG_FILE] == DEVICE_TYPE_TO_CONFIG_FILE[DEVICE_TYPE_INTESISBOX]
    assert data[CONF_CONFIG_FILE] == "intesisbox.yaml"
    assert data[CONF_TOKEN] == "001dc9a2c911"
    assert data[CONF_POLL_INTERVAL] == 45

    mock_open.assert_called_once_with("192.168.1.50", 3310)
    mock_writer.write.assert_called_once_with(b"ID\r\n")
    mock_writer.drain.assert_awaited_once()
    mock_reader.read.assert_awaited_once_with(1024)
    mock_writer.close.assert_called_once()
    mock_writer.wait_closed.assert_awaited_once()
    mock_resolve.assert_awaited_once_with(
        ip_address="192.168.1.50", mac_address="001dc9a2c911"
    )


async def test_step_intesisbox_hyphen_mac_and_fallbacks(hass: HomeAssistant) -> None:
    """Test hyphenated MAC normalization, fallback token, and user provided MAC preservation."""
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    # 1. Hyphenated MAC in ID packet
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"ID:IS-IR-WMP-1,AA-BB-CC-DD-EE-FF,192.168.1.60\r\n"
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch.object(
            flow, "_async_resolve_mac_and_set_unique_id", return_value=None
        ):
            res1 = await flow.async_step_intesisbox({CONF_IP_ADDRESS: "192.168.1.60"})
    assert res1["type"] == FlowResultType.CREATE_ENTRY
    assert res1["data"][CONF_TOKEN] == "aabbccddeeff"

    # 2. No ID packet and no MAC provided -> fallback to 'intesisbox'
    flow2 = ClimateIpConfigFlow()
    flow2.hass = hass
    flow2.context = {}

    mock_reader2 = AsyncMock()
    mock_reader2.read.return_value = b"NO_ID_HEADER\r\n"
    mock_writer2 = MagicMock()
    mock_writer2.drain = AsyncMock()
    mock_writer2.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader2, mock_writer2)):
        with patch.object(
            flow2, "_async_resolve_mac_and_set_unique_id", return_value=None
        ):
            res2 = await flow2.async_step_intesisbox({CONF_IP_ADDRESS: "192.168.1.70"})
    assert res2["type"] == FlowResultType.CREATE_ENTRY
    assert res2["data"][CONF_TOKEN] == "intesisbox"

    # 3. User supplied CONF_MAC in input is preserved
    flow3 = ClimateIpConfigFlow()
    flow3.hass = hass
    flow3.context = {}

    mock_reader3 = AsyncMock()
    mock_reader3.read.return_value = (
        b"ID:IS-IR-WMP-1,99:88:77:66:55:44,192.168.1.80\r\n"
    )
    mock_writer3 = MagicMock()
    mock_writer3.drain = AsyncMock()
    mock_writer3.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader3, mock_writer3)):
        with patch.object(
            flow3, "_async_resolve_mac_and_set_unique_id", return_value=None
        ):
            res3 = await flow3.async_step_intesisbox(
                {CONF_IP_ADDRESS: "192.168.1.80", CONF_MAC: "my_custom_mac"}
            )
    assert res3["type"] == FlowResultType.CREATE_ENTRY
    assert res3["data"][CONF_TOKEN] == "my_custom_mac"


async def test_step_intesisbox_user_mac_preserved_in_resolve_call(
    hass: HomeAssistant,
) -> None:
    """Kill L371 (mac_val=None), L397 (and→or), L426 (key→None).

    When the user supplies CONF_MAC, mac_val must be set from flow_data so that
    the 'and not mac_val' guard prevents auto-extraction from the ID response.
    Assert _async_resolve_mac_and_set_unique_id receives the USER mac, not the
    auto-extracted one. Also assert CONF_TOKEN equals the user mac via
    flow_data.get(CONF_MAC, ...) using the correct key.
    """
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    # Device responds with a DIFFERENT MAC in the ID packet
    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"ID:IS-IR-WMP-1,FFEEDDCCBBAA,192.168.1.90\r\n"
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch.object(
            flow, "_async_resolve_mac_and_set_unique_id", return_value=None
        ) as mock_resolve:
            result = await flow.async_step_intesisbox(
                {CONF_IP_ADDRESS: "192.168.1.90", CONF_MAC: "user_mac_value"}
            )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    mock_resolve.assert_awaited_once_with(
        ip_address="192.168.1.90", mac_address="user_mac_value"
    )
    assert result["data"][CONF_TOKEN] == "user_mac_value"


async def test_step_intesisbox_exact_timeout_values(hass: HomeAssistant) -> None:
    """Kill L388 (timeout=5.0→6.0) and L392 (timeout=5.0→None).

    Patch asyncio.wait_for to track all timeout kwarg values and assert
    both the open_connection and reader.read calls use exactly 5.0.
    """
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"ID:IS-IR-WMP-1,001DC9A2C911,192.168.1.50\r\n"
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    timeout_values: list = []
    _original_wait_for = asyncio.wait_for

    async def _tracking_wait_for(fut, **kwargs):
        timeout_values.append(kwargs.get("timeout"))
        return await _original_wait_for(fut, **kwargs)

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("asyncio.wait_for", new=_tracking_wait_for):
            with patch.object(
                flow, "_async_resolve_mac_and_set_unique_id", return_value=None
            ):
                result = await flow.async_step_intesisbox(
                    {CONF_IP_ADDRESS: "192.168.1.50"}
                )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert timeout_values == [5.0, 5.0], f"Expected [5.0, 5.0], got {timeout_values}"


async def test_step_intesisbox_malformed_id_no_model_field(
    hass: HomeAssistant,
) -> None:
    """Kill L398 (regex [^,]+→[^,]*).

    Send an ID packet with an empty model field ('ID:,MAC,...'). The regex
    uses [^,]+ which requires at least one non-comma char between 'ID:' and
    the first comma. An empty model means [^,]+ does NOT match → mac_val stays
    None → token falls back to 'intesisbox'. The [^,]* mutant would match the
    empty field and extract the MAC → different token.
    """
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"ID:,AABBCCDDEEFF,192.168.1.95\r\n"
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch.object(
            flow, "_async_resolve_mac_and_set_unique_id", return_value=None
        ) as mock_resolve:
            result = await flow.async_step_intesisbox({CONF_IP_ADDRESS: "192.168.1.95"})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TOKEN] == "intesisbox"
    mock_resolve.assert_awaited_once_with(ip_address="192.168.1.95", mac_address=None)


async def test_step_intesisbox_schema_empty_flow_data_defaults(
    hass: HomeAssistant,
) -> None:
    """Kill L437 (default=""→None) and L441 (suggested_value=""→None).

    Render the form with completely empty flow_data so that the fallback
    defaults in flow_data.get(CONF_IP_ADDRESS, "") and
    flow_data.get(CONF_MAC, "") are exercised. Assert they are empty strings,
    not None.
    """
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.flow_data = {}

    result = await flow.async_step_intesisbox(user_input=None)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "intesisbox"

    schema = result["data_schema"]

    ip_key = next(
        k for k in schema.schema if getattr(k, "schema", None) == CONF_IP_ADDRESS
    )
    assert ip_key.default() == ""

    mac_key = next(k for k in schema.schema if getattr(k, "schema", None) == CONF_MAC)
    assert mac_key.description == {"suggested_value": ""}


async def test_step_intesisbox_ascii_decode_non_ascii_bytes(
    hass: HomeAssistant,
) -> None:
    """Kill L393 (decode 'ascii' removed → defaults to utf-8).

    Send an ID response with non-ASCII bytes (\\xc3\\x84 = UTF-8 'Ä') placed
    between 'I' and 'D:'. Under ASCII decode with errors='ignore', the invalid
    bytes are stripped → "ID:MODEL,001DC9A2C911,..." → MAC extracted.
    Under UTF-8 decode (mutant), \\xc3\\x84 becomes 'Ä' → "IÄD:MODEL,..." →
    "ID:" NOT found → no MAC extraction → different token.
    """
    flow = ClimateIpConfigFlow()
    flow.hass = hass
    flow.context = {}

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"I\xc3\x84D:MODEL,001DC9A2C911,192.168.1.50\r\n"
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch.object(
            flow, "_async_resolve_mac_and_set_unique_id", return_value=None
        ) as mock_resolve:
            result = await flow.async_step_intesisbox({CONF_IP_ADDRESS: "192.168.1.50"})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TOKEN] == "001dc9a2c911"
    mock_resolve.assert_awaited_once_with(
        ip_address="192.168.1.50", mac_address="001dc9a2c911"
    )
