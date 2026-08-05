"""Tests for the Mempool config and options flows."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.const import (
    API_DIFFICULTY,
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    CONF_PRICE_ATTRIBUTES,
    CONF_VERIFY_SSL,
    DOMAIN,
    PUBLIC_FAST_INTERVAL,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import BASE_URL, PUBLIC_URL, mock_endpoints


async def _start_menu(hass: HomeAssistant) -> dict[str, Any]:
    """Open the flow and assert the instance-type menu is shown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    assert set(result["menu_options"]) == {"mempool_space", "self_hosted"}
    return result


async def _pick(hass: HomeAssistant, flow_id: str, option: str) -> dict[str, Any]:
    """Choose a menu option."""
    return await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": option}
    )


# --- public instance branch ---------------------------------------------------


async def test_public_full_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """The mempool.space branch validates, asks for a currency and creates."""
    mock_endpoints(aioclient_mock, PUBLIC_URL)

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "mempool_space")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "currency"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CURRENCY: "USD", CONF_PRICE_ATTRIBUTES: True},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Mempool (mempool.space)"
    assert result["data"] == {
        CONF_BASE_URL: PUBLIC_URL,
        CONF_VERIFY_SSL: True,
        # The public instance is polled gently and the interval is not offered.
        CONF_FAST_INTERVAL: PUBLIC_FAST_INTERVAL,
        CONF_CURRENCY: "USD",
        CONF_PRICE_ATTRIBUTES: True,
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_public_cannot_connect_aborts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An unreachable mempool.space aborts (there is nothing to correct)."""
    aioclient_mock.get(f"{PUBLIC_URL}{API_DIFFICULTY}", status=500)

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "mempool_space")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_public_duplicate_aborts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The public instance can only be added once."""
    MockConfigEntry(
        domain=DOMAIN, unique_id=PUBLIC_URL, data={CONF_BASE_URL: PUBLIC_URL}
    ).add_to_hass(hass)
    mock_endpoints(aioclient_mock, PUBLIC_URL)

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "mempool_space")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --- self-hosted branch -------------------------------------------------------


async def test_self_hosted_full_flow(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """The self-hosted branch collects a URL, then a currency, then creates."""
    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "self_hosted"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 30},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "currency"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CURRENCY: "EUR", CONF_PRICE_ATTRIBUTES: False},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Mempool (mempool.test)"
    assert result["data"] == {
        CONF_BASE_URL: BASE_URL,
        CONF_VERIFY_SSL: True,
        CONF_FAST_INTERVAL: 30,
        CONF_CURRENCY: "EUR",
        CONF_PRICE_ATTRIBUTES: False,
    }
    assert result["result"].unique_id == BASE_URL


async def test_self_hosted_trailing_slash_normalised(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """A trailing slash is stripped so the unique_id is stable."""
    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BASE_URL: f"{BASE_URL}/",
            CONF_VERIFY_SSL: True,
            CONF_FAST_INTERVAL: 60,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CURRENCY: "USD", CONF_PRICE_ATTRIBUTES: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == BASE_URL


async def test_self_hosted_cannot_connect_then_recovers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """A bad URL shows a form error, and the user can then finish the flow."""
    bad_url = "http://not-a-mempool.test"
    aioclient_mock.get(f"{bad_url}{API_DIFFICULTY}", status=404)
    mock_endpoints(aioclient_mock)

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: bad_url, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "self_hosted"
    assert result["errors"] == {"base": "cannot_connect"}

    # Same flow, corrected URL — the user gets all the way through.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CURRENCY: "USD", CONF_PRICE_ATTRIBUTES: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == BASE_URL


async def test_self_hosted_wrong_payload_is_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A URL that answers but is not a mempool API is rejected."""
    aioclient_mock.get(f"{BASE_URL}{API_DIFFICULTY}", json={"hello": "world"})

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_self_hosted_duplicate_aborts(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same instance URL cannot be configured twice."""
    mock_config_entry.add_to_hass(hass)

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_self_hosted_without_price_feed_skips_currency(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """An instance with no price feed goes straight to creating the entry."""
    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_CURRENCY not in result["data"]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # A bare list is not a price map.
        ([], False),
        # "time" is not a currency; -1 is the placeholder for an unsupported pair.
        ({"time": 1, "XBT": -1}, False),
        ({"time": 1, "USD": 95000}, True),
    ],
)
async def test_currency_probe_filters_non_currencies(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
    payload: Any,
    expected: bool,
) -> None:
    """Only positive 3-letter uppercase codes count as offered currencies."""
    mock_endpoints(aioclient_mock, prices=payload)

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )

    if expected:
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "currency"
    else:
        assert result["type"] is FlowResultType.CREATE_ENTRY


# --- options flow -------------------------------------------------------------


async def test_options_flow_self_hosted(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """A self-hosted entry can change interval, SSL and currency."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    schema_keys = {str(key) for key in result["data_schema"].schema}
    assert schema_keys == {
        CONF_FAST_INTERVAL,
        CONF_VERIFY_SSL,
        CONF_CURRENCY,
        CONF_PRICE_ATTRIBUTES,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_FAST_INTERVAL: 120,
            CONF_VERIFY_SSL: False,
            CONF_CURRENCY: "AUD",
            CONF_PRICE_ATTRIBUTES: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_FAST_INTERVAL] == 120
    assert mock_config_entry.options[CONF_CURRENCY] == "AUD"


async def test_options_flow_public_hides_connection_settings(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """The public instance's interval and SSL are fixed, so are not offered."""
    mock_endpoints(aioclient_mock, PUBLIC_URL)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=PUBLIC_URL,
        data={
            CONF_BASE_URL: PUBLIC_URL,
            CONF_VERIFY_SSL: True,
            CONF_FAST_INTERVAL: PUBLIC_FAST_INTERVAL,
            CONF_CURRENCY: "USD",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    schema_keys = {str(key) for key in result["data_schema"].schema}
    assert schema_keys == {CONF_CURRENCY, CONF_PRICE_ATTRIBUTES}


async def test_options_flow_without_price_feed(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """With no price feed the currency picker is omitted entirely."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    schema_keys = {str(key) for key in result["data_schema"].schema}
    assert schema_keys == {CONF_FAST_INTERVAL, CONF_VERIFY_SSL}


async def test_currency_default_falls_back_to_first_offered(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """With neither the HA currency nor USD on offer, the first fiat is default."""
    assert hass.config.currency not in ("AUD", "CAD")
    mock_endpoints(aioclient_mock, prices={"time": 1, "CAD": 130000, "AUD": 145000})

    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )

    assert result["step_id"] == "currency"
    key = next(k for k in result["data_schema"].schema if str(k) == CONF_CURRENCY)
    assert result["data_schema"].schema[key].config["options"] == ["AUD", "CAD"]
    assert key.default() == "AUD"


@pytest.mark.parametrize(
    "bad_url",
    [
        "not-a-url",
        "mynode.example:8999",  # scheme omitted — a realistic typo
        "ftp://mynode.example",
        "file:///etc/passwd",
        "http://",  # scheme but no host
        "",
    ],
)
async def test_self_hosted_rejects_non_http_urls(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, bad_url: str
) -> None:
    """Every request is built from this value, so it must be an http(s) URL.

    Rejected in the flow rather than surfacing as a confusing connection
    error, and without any request being attempted.
    """
    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: bad_url, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}
    assert aioclient_mock.call_count == 0


async def test_invalid_url_then_recovers(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """The user can correct a malformed URL and finish the flow."""
    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: "mempool.test", CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )
    assert result["errors"] == {"base": "invalid_url"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: BASE_URL, CONF_VERIFY_SSL: True, CONF_FAST_INTERVAL: 60},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CURRENCY: "USD", CONF_PRICE_ATTRIBUTES: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_surrounding_whitespace_is_trimmed(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """A pasted URL with stray whitespace still resolves to the same entry."""
    menu = await _start_menu(hass)
    result = await _pick(hass, menu["flow_id"], "self_hosted")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BASE_URL: f"  {BASE_URL}/  ",
            CONF_VERIFY_SSL: True,
            CONF_FAST_INTERVAL: 60,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CURRENCY: "USD", CONF_PRICE_ATTRIBUTES: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == BASE_URL
