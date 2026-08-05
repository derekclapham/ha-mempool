"""Shared fixtures for the Mempool integration tests.

Every host and URL here is a placeholder (``mempool.test``); nothing in this
directory refers to a real instance.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.const import (
    API_BLOCKS,
    API_DIFFICULTY,
    API_FEES,
    API_HASHRATE,
    API_HISTORICAL_PRICE,
    API_MEMPOOL,
    API_MEMPOOL_BLOCKS,
    API_MINING_POOLS,
    API_PRICES,
    API_REWARD_STATS,
    API_TIP_HEIGHT,
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    CONF_PRICE_ATTRIBUTES,
    CONF_VERIFY_SSL,
    DOMAIN,
)

# --- placeholders -------------------------------------------------------------

BASE_URL = "http://mempool.test"
PUBLIC_URL = "https://mempool.space"

# A fixed instant every time-sensitive assertion is anchored to. Tests that read
# a rolling-window sensor freeze the clock here via the `freezer` fixture.
NOW = datetime(2025, 10, 9, 12, 0, 0, tzinfo=UTC)
NOW_TS = int(NOW.timestamp())

TIP_HEIGHT = 960953

# --- payloads -----------------------------------------------------------------

DIFFICULTY: dict[str, Any] = {
    "progressPercent": 45.6,
    "difficultyChange": 2.34,
    "estimatedRetargetDate": 1760000000000,
    "remainingBlocks": 1096,
    "remainingTime": 657000000,
    "nextRetargetHeight": 962048,
}

FEES: dict[str, Any] = {
    "fastestFee": 5,
    "halfHourFee": 4,
    "hourFee": 3,
    "economyFee": 2,
    "minimumFee": 1,
}

MEMPOOL: dict[str, Any] = {
    "count": 12345,
    "vsize": 15_000_000,
    "total_fee": 50_000_000,
}

HASHRATE: dict[str, Any] = {
    "currentHashrate": 7.5e20,
    "currentDifficulty": 1.02e14,
}

PRICES: dict[str, Any] = {
    "time": NOW_TS,
    "USD": 95000,
    "EUR": 88000,
    "AUD": 145000,
}

# Tip block 5 min old, then three more inside the hour and one outside it, so
# `blocks_per_hour` is a deterministic 4.
BLOCKS: list[dict[str, Any]] = [
    {
        "height": TIP_HEIGHT,
        "timestamp": NOW_TS - 300,
        "tx_count": 3200,
        "size": 1_500_000,
        "weight": 3_990_000,
        "extras": {
            "reward": 315_000_000,
            "totalFees": 2_500_000,
            "medianFee": 4.5,
            "pool": {"name": "PoolAlpha"},
        },
    },
    {"height": TIP_HEIGHT - 1, "timestamp": NOW_TS - 1500, "tx_count": 3000},
    {"height": TIP_HEIGHT - 2, "timestamp": NOW_TS - 2400, "tx_count": 2900},
    {"height": TIP_HEIGHT - 3, "timestamp": NOW_TS - 3300, "tx_count": 2800},
    {"height": TIP_HEIGHT - 4, "timestamp": NOW_TS - 5000, "tx_count": 2700},
]

MEMPOOL_BLOCKS: list[dict[str, Any]] = [
    {"nTx": 3000, "medianFee": 4.2},
    {"nTx": 2800, "medianFee": 3.1},
    {"nTx": 2000, "medianFee": 2.0},
]

MINING_POOLS: dict[str, Any] = {
    "pools": [
        {"name": "PoolAlpha", "blockCount": 300, "rank": 1},
        {"name": "PoolBeta", "blockCount": 200, "rank": 2},
        {"name": "PoolGamma", "blockCount": 100, "rank": 3},
    ]
}

REWARD_STATS: dict[str, Any] = {
    "totalReward": "46000000000",
    "totalFee": "600000000",
    "totalTx": "400000",
}

HISTORICAL_PRICE: dict[str, Any] = {
    "prices": [
        {"time": NOW_TS - 7200, "USD": 94000},
        {"time": NOW_TS - 3600, "USD": 94500},
        {"time": NOW_TS, "USD": 95000},
    ]
}


def mock_endpoints(
    aioclient_mock: AiohttpClientMocker,
    base_url: str = BASE_URL,
    *,
    prices: dict[str, Any] | None = PRICES,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Register a full, healthy set of API responses for `base_url`.

    Pass ``prices=None`` to model an instance with the optional price feed
    switched off (the endpoint 404s). Pass ``overrides`` — a mapping of API path
    to ``aioclient_mock.get`` keyword arguments — to replace one endpoint's
    response while leaving the rest healthy.
    """
    overrides = overrides or {}

    def register(path: str, **kwargs: Any) -> None:
        aioclient_mock.get(f"{base_url}{path}", **overrides.get(path, kwargs))

    register(API_TIP_HEIGHT, text=str(TIP_HEIGHT))
    register(API_DIFFICULTY, json=DIFFICULTY)
    register(API_FEES, json=FEES)
    register(API_MEMPOOL, json=MEMPOOL)
    register(API_HASHRATE, json=HASHRATE)
    register(API_BLOCKS, json=BLOCKS)
    register(API_MEMPOOL_BLOCKS, json=MEMPOOL_BLOCKS)
    register(API_MINING_POOLS, json=MINING_POOLS)
    register(API_REWARD_STATS, json=REWARD_STATS)
    register(API_HISTORICAL_PRICE, json=HISTORICAL_PRICE)
    if prices is None:
        register(API_PRICES, status=404)
    else:
        register(API_PRICES, json=prices)


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """A healthy self-hosted instance serving every endpoint."""
    mock_endpoints(aioclient_mock)
    return aioclient_mock


@pytest.fixture
def mock_api_no_price(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """A self-hosted instance with the optional price feed disabled."""
    mock_endpoints(aioclient_mock, prices=None)
    return aioclient_mock


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A configured self-hosted entry with a price currency."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Mempool (mempool.test)",
        unique_id=BASE_URL,
        data={
            CONF_BASE_URL: BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_FAST_INTERVAL: 60,
            CONF_CURRENCY: "USD",
            CONF_PRICE_ATTRIBUTES: False,
        },
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Stop config-flow tests from actually setting the integration up."""
    with patch(
        "custom_components.mempool.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture
def enable_all_entities() -> Generator[None]:
    """Register every entity, including those disabled by default.

    Mirrors Home Assistant core's `entity_registry_enabled_by_default`, which
    pytest-homeassistant-custom-component does not re-export. Tests asserting
    on values need it, since nine sensors ship switched off.
    """
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
    ):
        yield
