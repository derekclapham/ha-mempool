"""Thin async client for a mempool REST API (self-hosted or mempool.space)."""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from .const import (
    API_DIFFICULTY,
    API_FEES,
    API_HASHRATE,
    API_HISTORICAL_PRICE,
    API_MEMPOOL,
    API_PRICES,
    API_TIP_HEIGHT,
)

# A generous single timeout covers connect + read. A slow/unreachable node
# surfaces as MempoolApiError, which the coordinators turn into UpdateFailed.
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class MempoolApiError(Exception):
    """Raised when the mempool API cannot be reached or returns junk."""


class MempoolClient:
    """Minimal client over the endpoints the integration needs.

    Stateless apart from the base URL; it borrows Home Assistant's shared
    aiohttp session rather than opening its own, so there is nothing to close.
    """

    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        """Store the shared HA aiohttp session and the instance base URL."""
        self._session = session
        # Normalise so joining "/api/..." never produces a double slash.
        self._base = base_url.rstrip("/")

    @property
    def base_url(self) -> str:
        """Return the configured base URL."""
        return self._base

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a path and parse JSON, tolerating bare-scalar bodies.

        Every network/HTTP failure is normalised to MempoolApiError so callers
        only have one exception type to catch. `json.loads` also parses bare
        scalars, so the plain-integer `tip/height` body round-trips fine.
        """
        url = f"{self._base}{path}"
        try:
            async with self._session.get(
                url, params=params, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                text = (await resp.text()).strip()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MempoolApiError(f"Error fetching {path}: {err}") from err

        try:
            return json.loads(text)
        except ValueError as err:
            # e.g. an HTML error page from a reverse proxy in front of the node.
            raise MempoolApiError(f"Invalid JSON from {path}: {text[:80]!r}") from err

    async def tip_height(self) -> int:
        """Current chain tip height (endpoint returns a bare integer)."""
        return int(await self._get(API_TIP_HEIGHT))

    async def difficulty_adjustment(self) -> dict[str, Any]:
        """Difficulty adjustment progress / ETA / projected change."""
        return await self._get(API_DIFFICULTY)

    async def fees_recommended(self) -> dict[str, Any]:
        """Recommended fee tiers in sat/vB."""
        return await self._get(API_FEES)

    async def mempool(self) -> dict[str, Any]:
        """Mempool summary (tx count, vsize, total fee)."""
        return await self._get(API_MEMPOOL)

    async def hashrate(self) -> dict[str, Any]:
        """Mining hashrate + current difficulty."""
        return await self._get(API_HASHRATE)

    async def prices(self) -> dict[str, Any]:
        """Current spot price across the fiats the instance publishes."""
        return await self._get(API_PRICES)

    async def historical_price(self, currency: str) -> dict[str, Any]:
        """Historical spot price for a currency (if the price feed is on)."""
        return await self._get(API_HISTORICAL_PRICE, {"currency": currency})
