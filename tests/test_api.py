"""Tests for the thin mempool REST client."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.api import MempoolApiError, MempoolClient
from custom_components.mempool.const import (
    API_BLOCKS,
    API_DIFFICULTY,
    API_HISTORICAL_PRICE,
    API_MEMPOOL,
    API_TIP_HEIGHT,
)
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


# --- hardening ----------------------------------------------------------------


async def test_stdlib_json_accepts_bare_constants() -> None:
    """Establish the premise for the test below.

    `json.loads` is not strict by default: it parses `NaN` and `Infinity`
    into floats, which is why the client has to opt out explicitly.
    """
    import json
    import math

    assert math.isnan(json.loads("NaN"))
    assert math.isinf(json.loads("Infinity"))


@pytest.mark.parametrize(
    "body",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        '{"progressPercent": NaN}',
        '{"currentHashrate": Infinity}',
    ],
)
async def test_rejects_bare_json_constants(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: str
) -> None:
    """NaN/Infinity would flow into states and statistics; refuse them."""
    aioclient_mock.get(f"{BASE_URL}{API_DIFFICULTY}", text=body)

    with pytest.raises(MempoolApiError, match="Invalid JSON"):
        await _client(hass).difficulty_adjustment()


async def test_rejects_oversized_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A body over the cap is abandoned rather than buffered whole."""
    body = json.dumps({"progressPercent": 1.0, "pad": "x" * 4000})
    aioclient_mock.get(f"{BASE_URL}{API_DIFFICULTY}", text=body)

    with (
        patch("custom_components.mempool.api._MAX_RESPONSE_BYTES", len(body) - 1),
        pytest.raises(MempoolApiError, match="exceeded"),
    ):
        await _client(hass).difficulty_adjustment()


async def test_accepts_body_exactly_at_the_cap(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The benign path: a body right on the limit still parses.

    Guards the off-by-one that would make the cap reject valid responses.
    """
    body = json.dumps({"progressPercent": 1.0, "pad": "x" * 4000})
    aioclient_mock.get(f"{BASE_URL}{API_DIFFICULTY}", text=body)

    with patch("custom_components.mempool.api._MAX_RESPONSE_BYTES", len(body)):
        assert await _client(hass).difficulty_adjustment() == json.loads(body)


async def test_real_world_body_is_well_under_the_cap() -> None:
    """The cap has room for the largest endpoint by a wide margin.

    historical-price measured ~1 MB on the public instance and grows by
    roughly 65 KB a year, so 16 MiB is decades of headroom.
    """
    from custom_components.mempool.api import _MAX_RESPONSE_BYTES

    assert _MAX_RESPONSE_BYTES >= 16 * 1024 * 1024


async def test_non_utf8_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A body that is not UTF-8 is a clean error, not a decode traceback."""
    aioclient_mock.get(f"{BASE_URL}{API_DIFFICULTY}", content=b"\xff\xfe\x00bad")

    with pytest.raises(MempoolApiError, match="Non-UTF-8"):
        await _client(hass).difficulty_adjustment()


# --- response shape validation ------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (API_MEMPOOL, "[1, 2, 3]"),
        (API_MEMPOOL, "42"),
        (API_MEMPOOL, "null"),
    ],
)
async def test_endpoint_expecting_an_object_rejects_other_shapes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    path: str,
    body: str,
) -> None:
    """A wrong-shaped payload is a clean error, not an AttributeError later.

    Without this the value would flow into a sensor's value_fn and blow up
    there, well away from the endpoint that actually misbehaved.
    """
    aioclient_mock.get(f"{BASE_URL}{path}", text=body)

    with pytest.raises(MempoolApiError, match="Expected a JSON object"):
        await _client(hass).mempool()


@pytest.mark.parametrize("body", ['{"not": "an array"}', "7"])
async def test_endpoint_expecting_an_array_rejects_other_shapes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: str
) -> None:
    """The blocks endpoints must answer with a JSON array."""
    aioclient_mock.get(f"{BASE_URL}{API_BLOCKS}", text=body)

    with pytest.raises(MempoolApiError, match="Expected a JSON array"):
        await _client(hass).blocks()


async def test_historical_price_accepts_both_shapes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Object and bare-array payloads are both accepted."""
    aioclient_mock.get(
        f"{BASE_URL}{API_HISTORICAL_PRICE}", json={"prices": [{"time": 1, "USD": 2}]}
    )
    assert await _client(hass).historical_price("USD") == {
        "prices": [{"time": 1, "USD": 2}]
    }

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE_URL}{API_HISTORICAL_PRICE}", json=[{"time": 1, "USD": 2}]
    )
    assert await _client(hass).historical_price("USD") == [{"time": 1, "USD": 2}]


async def test_historical_price_rejects_a_scalar(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Anything that is neither object nor array is still an error."""
    aioclient_mock.get(f"{BASE_URL}{API_HISTORICAL_PRICE}", text="123")

    with pytest.raises(MempoolApiError, match="Expected a JSON object or array"):
        await _client(hass).historical_price("USD")
