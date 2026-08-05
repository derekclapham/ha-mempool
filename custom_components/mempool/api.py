"""Thin async client for a mempool REST API (self-hosted or mempool.space)."""

from __future__ import annotations

import json
from math import isfinite
from typing import Any, NoReturn

import aiohttp

from .const import (
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
    MAX_BLOCK_HEIGHT,
    MAX_LIST_ITEMS,
)

# A generous single timeout covers connect + read. A slow/unreachable node
# surfaces as MempoolApiError, which the coordinators turn into UpdateFailed.
_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Cap on the *decompressed* body we will hold in memory. aiohttp transparently
# inflates gzip, so without this a small compressed reply from a hostile or
# misconfigured host could expand to hundreds of megabytes before we ever
# reach the parser. The largest endpoint by a wide margin is historical-price:
# measured at ~1 MB on the public instance, growing by roughly 65 KB a year as
# the series lengthens. 16 MiB leaves decades of headroom.
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024


class MempoolApiError(Exception):
    """Raised when the mempool API cannot be reached or returns junk."""


def _reject_json_constant(value: str) -> NoReturn:
    """Refuse the bare literals `json.loads` accepts outside strict JSON.

    By default `json.loads` parses `NaN`, `Infinity` and `-Infinity` into
    floats. Those would flow straight into sensor states and long-term
    statistics, where they are neither meaningful nor recoverable.
    """
    raise ValueError(f"unsupported JSON constant {value}")


def _strict_float(value: str) -> float:
    """Parse a JSON number, refusing anything that is not finite.

    Rejecting the bare `Infinity` and `NaN` literals is not sufficient on its
    own: an ordinary-looking numeric literal that overflows a float, such as
    `1e400`, also parses to infinity and reaches sensor states the same way.
    This runs on every float in the body, so both spellings are caught at the
    point of parsing rather than being chased through the code that uses them.
    """
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value}")
    return parsed


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
                text = (await self._read_capped(resp, path)).strip()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MempoolApiError(f"Error fetching {path}: {err}") from err

        try:
            return json.loads(
                text,
                parse_constant=_reject_json_constant,
                parse_float=_strict_float,
            )
        except ValueError as err:
            # e.g. an HTML error page from a reverse proxy in front of the node.
            raise MempoolApiError(f"Invalid JSON from {path}: {text[:80]!r}") from err

    async def _get_dict(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GET a path that must answer with a JSON object.

        Checking the shape here rather than trusting it means a proxy or a
        misbehaving instance returning, say, a list surfaces as MempoolApiError
        — which the coordinators already turn into a clean UpdateFailed —
        instead of an AttributeError deep inside a sensor's value_fn.
        """
        data = await self._get(path, params)
        if not isinstance(data, dict):
            raise MempoolApiError(
                f"Expected a JSON object from {path}, got {type(data).__name__}"
            )
        return data

    async def _get_list(self, path: str) -> list[dict[str, Any]]:
        """GET a path that must answer with a JSON array.

        Truncated rather than rejected past the cap: the endpoints returning
        arrays are ordered newest-first, so the entries the sensors read are at
        the front and an over-long tail is simply discarded.
        """
        data = await self._get(path)
        if not isinstance(data, list):
            raise MempoolApiError(
                f"Expected a JSON array from {path}, got {type(data).__name__}"
            )
        return data[:MAX_LIST_ITEMS]

    @staticmethod
    async def _read_capped(resp: aiohttp.ClientResponse, path: str) -> str:
        """Read a response body, refusing to buffer more than the cap.

        Read in chunks rather than via `resp.text()` so an oversized body is
        abandoned partway instead of being fully materialised first.
        """
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.content.iter_chunked(_CHUNK_BYTES):
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                raise MempoolApiError(
                    f"Response from {path} exceeded {_MAX_RESPONSE_BYTES} bytes"
                )
            chunks.append(chunk)

        try:
            return b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError as err:
            raise MempoolApiError(f"Non-UTF-8 response from {path}") from err

    async def tip_height(self) -> int:
        """Current chain tip height (endpoint returns a bare integer).

        Range-checked here rather than downstream. The height is fed into an
        exponent when the block subsidy is derived, so an absurd value does not
        produce a wrong answer -- it produces unbounded work. Rejecting it at
        ingest fails the poll cleanly, which the coordinator already turns into
        unavailable sensors and a single log line.
        """
        raw = await self._get(API_TIP_HEIGHT)
        try:
            height = int(raw)
        except (TypeError, ValueError, OverflowError) as err:
            raise MempoolApiError(
                f"Chain tip height is not an integer: {type(raw).__name__}"
            ) from err
        if not 0 <= height <= MAX_BLOCK_HEIGHT:
            raise MempoolApiError(f"Implausible chain tip height: {height}")
        return height

    async def difficulty_adjustment(self) -> dict[str, Any]:
        """Difficulty adjustment progress / ETA / projected change."""
        return await self._get_dict(API_DIFFICULTY)

    async def fees_recommended(self) -> dict[str, Any]:
        """Recommended fee tiers in sat/vB."""
        return await self._get_dict(API_FEES)

    async def mempool(self) -> dict[str, Any]:
        """Mempool summary (tx count, vsize, total fee)."""
        return await self._get_dict(API_MEMPOOL)

    async def hashrate(self) -> dict[str, Any]:
        """Mining hashrate + current difficulty."""
        return await self._get_dict(API_HASHRATE)

    async def prices(self) -> dict[str, Any]:
        """Current spot price across the fiats the instance publishes."""
        return await self._get_dict(API_PRICES)

    async def historical_price(
        self, currency: str
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Historical spot price for a currency (if the price feed is on).

        Current instances answer with {"prices": [...]}, but the caller has
        always tolerated a bare array as well and that tolerance is kept rather
        than narrowed: it costs nothing, and it is not worth breaking an
        instance running an older build to tidy up a return type.
        """
        data = await self._get(API_HISTORICAL_PRICE, {"currency": currency})
        if isinstance(data, dict | list):
            return data
        raise MempoolApiError(
            f"Expected a JSON object or array from {API_HISTORICAL_PRICE}, "
            f"got {type(data).__name__}"
        )

    async def blocks(self) -> list[dict[str, Any]]:
        """Recent blocks, newest first (index 0 is the chain tip)."""
        return await self._get_list(API_BLOCKS)

    async def mempool_blocks(self) -> list[dict[str, Any]]:
        """Projected upcoming blocks from the current mempool."""
        return await self._get_list(API_MEMPOOL_BLOCKS)

    async def mining_pools(self) -> dict[str, Any]:
        """Mining pool distribution over the last week."""
        return await self._get_dict(API_MINING_POOLS)

    async def reward_stats(self) -> dict[str, Any]:
        """Reward/fee totals over the last 144 blocks (~24h)."""
        return await self._get_dict(API_REWARD_STATS)
