"""Tests for the Mempool diagnostics.

The governing assumption here is that a diagnostics download ends up pasted
into a public issue, so the tests check the whole serialised blob for anything
identifying rather than checking individual keys — a key-by-key test passes
happily while the same hostname leaks through a field nobody thought about.
"""

from __future__ import annotations

import json

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.const import CONF_BASE_URL, DOMAIN
from custom_components.mempool.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant

from .conftest import BASE_URL, PUBLIC_URL, TIP_HEIGHT, mock_endpoints

# The host portion of the placeholder base URL. For a real self-hosted user
# this is an internal hostname, which is exactly what must not leak.
SECRET_HOST = "mempool.test"


async def _diagnostics(
    hass: HomeAssistant, entry: MockConfigEntry
) -> dict:
    """Set an entry up and collect its diagnostics."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await async_get_config_entry_diagnostics(hass, entry)


async def test_diagnostics_never_leak_the_host(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The instance hostname appears nowhere in the output.

    Checked against the whole serialised document, because the host reaches
    the entry by three routes: the base_url key, the config entry unique_id,
    and the entry title, which is built from the host.
    """
    diagnostics = await _diagnostics(hass, mock_config_entry)

    # The premise: this entry really does carry the host in all three places.
    assert SECRET_HOST in mock_config_entry.data[CONF_BASE_URL]
    assert SECRET_HOST in mock_config_entry.unique_id
    assert SECRET_HOST in mock_config_entry.title

    blob = json.dumps(diagnostics, default=str)
    assert SECRET_HOST not in blob
    assert BASE_URL not in blob


async def test_diagnostics_redact_base_url(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The base URL is present but redacted, not silently dropped."""
    diagnostics = await _diagnostics(hass, mock_config_entry)

    assert CONF_BASE_URL in diagnostics["entry"]["data"]
    assert diagnostics["entry"]["data"][CONF_BASE_URL] == "**REDACTED**"


async def test_diagnostics_redact_base_url_in_options(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Options are redacted with the same list as data."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_BASE_URL: BASE_URL, "currency": "USD"}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["entry"]["options"][CONF_BASE_URL] == "**REDACTED**"
    assert SECRET_HOST not in json.dumps(diagnostics, default=str)


async def test_diagnostics_identify_the_instance_kind(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Which kind of instance is in use survives redaction."""
    diagnostics = await _diagnostics(hass, mock_config_entry)

    assert diagnostics["instance"] == "self-hosted"


async def test_diagnostics_name_the_public_instance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """mempool.space is not a secret, and knowing it is useful in a report."""
    mock_endpoints(aioclient_mock, PUBLIC_URL)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mempool (mempool.space)",
        unique_id=PUBLIC_URL,
        data={CONF_BASE_URL: PUBLIC_URL, "fast_interval": 300, "currency": "USD"},
    )

    diagnostics = await _diagnostics(hass, entry)

    assert diagnostics["instance"] == "mempool.space (public)"


async def test_diagnostics_include_coordinator_payloads(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Public chain data is included -- that is the point of the download."""
    diagnostics = await _diagnostics(hass, mock_config_entry)

    coordinators = diagnostics["coordinators"]
    assert set(coordinators) == {"fast", "slow", "price"}
    assert coordinators["fast"]["data"]["height"] == TIP_HEIGHT
    assert coordinators["fast"]["last_update_success"] is True
    assert coordinators["fast"]["update_interval"] == 60
    assert coordinators["slow"]["data"]["difficulty"]["progressPercent"] == 45.6
    assert coordinators["price"]["data"]["prices"]["USD"] == 95000


async def test_diagnostics_without_price_feed(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An instance with no price feed omits that coordinator cleanly."""
    diagnostics = await _diagnostics(hass, mock_config_entry)

    assert diagnostics["price_feed_available"] is False
    assert set(diagnostics["coordinators"]) == {"fast", "slow"}


async def test_diagnostics_are_json_serialisable(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Home Assistant serialises the download, so it must contain no objects."""
    diagnostics = await _diagnostics(hass, mock_config_entry)

    # No default= here: anything not natively serialisable is a failure.
    json.dumps(diagnostics)
