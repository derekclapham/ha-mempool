"""Tests for the missing-price-feed repair issue."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.const import (
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .conftest import BASE_URL, PUBLIC_URL, mock_endpoints


def _issue(
    hass: HomeAssistant, entry: MockConfigEntry
) -> ir.IssueEntry | None:
    """The price-feed issue for one entry, if it is raised."""
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"price_feed_unavailable_{entry.entry_id}"
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_issue_raised_when_feed_missing(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A self-hosted instance with the price feed off gets a repair issue."""
    await _setup(hass, mock_config_entry)

    issue = _issue(hass, mock_config_entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "price_feed_unavailable"
    assert issue.translation_placeholders["currency"] == "USD"
    # Not fixable in a flow: the user has to change their own instance.
    assert issue.is_fixable is False


async def test_no_issue_when_feed_present(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A healthy price feed raises nothing."""
    await _setup(hass, mock_config_entry)

    assert _issue(hass, mock_config_entry) is None


async def test_issue_clears_when_the_feed_comes_back(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The resolve direction: fixing the feed clears the issue on reload.

    The failure this guards against is an issue that is raised correctly and
    then lingers forever after the user has done what it asked.
    """
    mock_endpoints(aioclient_mock, prices=None)
    await _setup(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is not None

    # The user switches the price feed on, then the entry reloads.
    aioclient_mock.clear_requests()
    mock_endpoints(aioclient_mock)
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, mock_config_entry) is None


async def test_no_issue_for_the_public_instance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A public-instance outage is not something the user can repair.

    The rule is explicit that repair issues must be actionable, so the public
    branch keeps the log warning and raises nothing.
    """
    mock_endpoints(aioclient_mock, PUBLIC_URL, prices=None)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mempool (mempool.space)",
        unique_id=PUBLIC_URL,
        data={
            CONF_BASE_URL: PUBLIC_URL,
            CONF_FAST_INTERVAL: 300,
            CONF_CURRENCY: "USD",
        },
    )
    await _setup(hass, entry)

    assert _issue(hass, entry) is None


async def test_no_issue_without_a_currency(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
) -> None:
    """An entry that never wanted a price sensor is not missing anything."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=BASE_URL,
        data={CONF_BASE_URL: BASE_URL, CONF_FAST_INTERVAL: 60},
    )
    await _setup(hass, entry)

    assert _issue(hass, entry) is None


async def test_issue_removed_with_the_entry(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Deleting the entry takes its repair issue with it."""
    await _setup(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is not None

    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, mock_config_entry) is None
