"""Tests for the thin mempool REST client."""

from __future__ import annotations

import asyncio

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.api import MempoolApiError, MempoolClient
from custom_components.mempool.const import API_DIFFICULTY, API_TIP_HEIGHT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import BASE_URL, TIP_HEIGHT, mock_endpoints


def _client(hass: HomeAssistant, base_url: str = BASE_URL) -> MempoolClient:
    """Build a client on the test session."""
    return MempoolClient(async_get_clientsession(hass), base_url)


async def test_base_url_is_normalised(hass: HomeAssistant) -> None:
    """A trailing slash is stripped so paths never double up."""
    assert _client(hass, f"{BASE_URL}/").base_url == BASE_URL
    assert _client(hass, f"{BASE_URL}///").base_url == BASE_URL


async def test_bare_scalar_body(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """`tip/height` returns a bare integer, not a JSON object."""
    assert await _client(hass).tip_height() == TIP_HEIGHT


async def test_every_endpoint(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """Each client method reaches its endpoint and parses the body."""
    client = _client(hass)

    assert "progressPercent" in await client.difficulty_adjustment()
    assert "fastestFee" in await client.fees_recommended()
    assert "count" in await client.mempool()
    assert "currentHashrate" in await client.hashrate()
    assert "USD" in await client.prices()
    assert "prices" in await client.historical_price("USD")
    assert isinstance(await client.blocks(), list)
    assert isinstance(await client.mempool_blocks(), list)
    assert "pools" in await client.mining_pools()
    assert "totalReward" in await client.reward_stats()


async def test_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A non-2xx response becomes MempoolApiError."""
    aioclient_mock.get(f"{BASE_URL}{API_TIP_HEIGHT}", status=503)

    with pytest.raises(MempoolApiError, match="Error fetching"):
        await _client(hass).tip_height()


async def test_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A transport failure becomes MempoolApiError."""
    aioclient_mock.get(f"{BASE_URL}{API_TIP_HEIGHT}", exc=TimeoutError())

    with pytest.raises(MempoolApiError):
        await _client(hass).tip_height()


async def test_invalid_json(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An HTML error page from a reverse proxy becomes MempoolApiError."""
    aioclient_mock.get(
        f"{BASE_URL}{API_DIFFICULTY}", text="<html><body>502</body></html>"
    )

    with pytest.raises(MempoolApiError, match="Invalid JSON"):
        await _client(hass).difficulty_adjustment()


async def test_error_message_is_truncated(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A huge junk body does not end up whole in the log line."""
    aioclient_mock.get(f"{BASE_URL}{API_DIFFICULTY}", text="x" * 5000)

    with pytest.raises(MempoolApiError) as err:
        await _client(hass).difficulty_adjustment()

    assert len(str(err.value)) < 200


async def test_concurrent_fetches(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """The coordinators gather several endpoints at once."""
    client = _client(hass)
    results = await asyncio.gather(
        client.tip_height(), client.fees_recommended(), client.mempool()
    )
    assert results[0] == TIP_HEIGHT


async def test_paths_are_joined_without_double_slash(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A base URL with a trailing slash still hits the canonical path."""
    mock_endpoints(aioclient_mock)
    await _client(hass, f"{BASE_URL}/").tip_height()

    assert str(aioclient_mock.mock_calls[0][1]) == f"{BASE_URL}{API_TIP_HEIGHT}"
