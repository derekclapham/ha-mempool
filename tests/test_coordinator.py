"""Tests for the coordinator base class."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.api import MempoolApiError, MempoolClient
from custom_components.mempool.const import (
    API_TIP_HEIGHT,
    PRICE_INTERVAL,
    SLOW_INTERVAL,
)
from custom_components.mempool.coordinator import _BaseCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .conftest import BASE_URL, mock_endpoints


async def test_base_fetch_is_abstract(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The shared base class leaves `_fetch` to its subclasses."""
    mock_config_entry.add_to_hass(hass)
    coordinator = _BaseCoordinator(
        hass,
        mock_config_entry,
        MempoolClient(async_get_clientsession(hass), BASE_URL),
        "test",
        timedelta(seconds=60),
    )

    with pytest.raises(NotImplementedError):
        await coordinator._fetch()


async def test_api_error_becomes_update_failed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Our error type is translated into the coordinator's UpdateFailed."""
    mock_config_entry.add_to_hass(hass)

    class _Failing(_BaseCoordinator):
        async def _fetch(self) -> dict:
            raise MempoolApiError("node unreachable")

    coordinator = _Failing(
        hass,
        mock_config_entry,
        MempoolClient(async_get_clientsession(hass), BASE_URL),
        "test",
        timedelta(seconds=60),
    )

    with pytest.raises(UpdateFailed, match="node unreachable"):
        await coordinator._async_update_data()


async def test_logs_once_when_unavailable_and_again_on_recovery(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unavailability is logged once, not on every failed poll.

    This behaviour is inherited from DataUpdateCoordinator rather than written
    here, which is exactly why it is worth pinning: the integration satisfies
    log-when-unavailable only for as long as it keeps raising UpdateFailed.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data.fast

    def our_records(level: str) -> list[str]:
        return [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("custom_components.mempool")
            and record.levelname == level
        ]

    # Two consecutive failures.
    caplog.clear()
    mock_api.clear_requests()
    mock_endpoints(mock_api, overrides={API_TIP_HEIGHT: {"status": 500}})
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    errors = our_records("ERROR")
    assert len(errors) == 1, f"expected one error log, got {errors}"
    assert "Error fetching mempool fast data" in errors[0]

    # Recovery.
    caplog.clear()
    mock_api.clear_requests()
    mock_endpoints(mock_api)
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert our_records("INFO") == ["Fetching mempool fast data recovered"]


async def test_each_coordinator_logs_under_its_own_name(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The three coordinators are named, so a log line says which one failed."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    runtime = mock_config_entry.runtime_data
    assert runtime.fast.name == "mempool fast"
    assert runtime.slow.name == "mempool slow"
    assert runtime.price.name == "mempool price"


async def test_poll_intervals(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Each group polls at the rate its data actually changes."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    runtime = mock_config_entry.runtime_data
    # The fast group is the configured one; the other two are fixed.
    assert runtime.fast.update_interval == timedelta(seconds=60)
    assert runtime.price.update_interval == PRICE_INTERVAL
    assert runtime.slow.update_interval == SLOW_INTERVAL
