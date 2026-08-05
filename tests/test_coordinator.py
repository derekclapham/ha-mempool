"""Tests for the coordinator base class."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mempool.api import MempoolApiError, MempoolClient
from custom_components.mempool.coordinator import _BaseCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .conftest import BASE_URL


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
