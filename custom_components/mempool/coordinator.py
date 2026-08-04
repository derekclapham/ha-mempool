"""Data update coordinators for the Mempool integration.

Three coordinators grouped by how fast each datum actually changes, so a LAN
node is polled sensibly and a public instance can be polled gently:

* fast  — chain tip, recommended fees, mempool summary (user-configurable)
* price — spot price across fiats
* slow  — difficulty adjustment, hashrate / difficulty
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MempoolApiError, MempoolClient
from .const import DOMAIN, LOGGER, PRICE_INTERVAL, SLOW_INTERVAL


@dataclass
class MempoolData:
    """Everything a config entry keeps alive at runtime.

    Stored on `entry.runtime_data`; the sensor platform and the backfill
    service read the coordinators and client back out of here. `price` is None
    when the instance has no price feed (or no currency was chosen).
    """

    client: MempoolClient
    currency: str | None
    price_attributes: bool  # expose the other fiats as price-sensor attributes
    fast: MempoolFastCoordinator
    slow: MempoolSlowCoordinator
    price: MempoolPriceCoordinator | None


# Typed config entry alias — lets `entry.runtime_data` be known as MempoolData.
type MempoolConfigEntry = ConfigEntry[MempoolData]


class _BaseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Shared plumbing; subclasses implement `_fetch`.

    Each coordinator owns one poll timer and exposes its latest payload as a
    plain dict on `self.data`, which the sensors index into via their value_fn.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: MempoolClient,
        name: str,
        interval: timedelta,
    ) -> None:
        """Initialise a named coordinator with its own poll interval."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {name}",
            update_interval=interval,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll callback; translate our error type into HA's UpdateFailed."""
        try:
            return await self._fetch()
        except MempoolApiError as err:
            # UpdateFailed flips the coordinator (and its entities) to
            # unavailable and schedules a retry, rather than logging a traceback.
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> dict[str, Any]:
        """Fetch this group's endpoints. Implemented by each subclass."""
        raise NotImplementedError


class MempoolFastCoordinator(_BaseCoordinator):
    """Chain tip, fees and mempool summary (the user-tunable group)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: MempoolClient,
        interval: timedelta,
    ) -> None:
        """Initialise with the user-configurable fast interval."""
        super().__init__(hass, entry, client, "fast", interval)

    async def _fetch(self) -> dict[str, Any]:
        # Fetch the endpoints concurrently; any one failing raises and
        # (via _async_update_data) fails the whole cycle, which is what we want.
        height, fees, mempool, blocks, projected = await asyncio.gather(
            self.client.tip_height(),
            self.client.fees_recommended(),
            self.client.mempool(),
            self.client.blocks(),
            self.client.mempool_blocks(),
        )
        return {
            "height": height,
            "fees": fees,
            "mempool": mempool,
            "blocks": blocks,
            "projected": projected,
        }


class MempoolSlowCoordinator(_BaseCoordinator):
    """Difficulty adjustment and hashrate (change on the scale of days)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: MempoolClient
    ) -> None:
        """Initialise on the slow interval."""
        super().__init__(hass, entry, client, "slow", SLOW_INTERVAL)

    async def _fetch(self) -> dict[str, Any]:
        difficulty, hashrate, pools, rewards = await asyncio.gather(
            self.client.difficulty_adjustment(),
            self.client.hashrate(),
            self.client.mining_pools(),
            self.client.reward_stats(),
        )
        return {
            "difficulty": difficulty,
            "hashrate": hashrate,
            "pools": pools,
            "rewards": rewards,
        }


class MempoolPriceCoordinator(_BaseCoordinator):
    """Spot price across fiats (only created when a price feed exists)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: MempoolClient
    ) -> None:
        """Initialise on the price interval."""
        super().__init__(hass, entry, client, "price", PRICE_INTERVAL)

    async def _fetch(self) -> dict[str, Any]:
        # Nest under a "prices" key so the payload shape matches the other
        # coordinators (a dict the sensor value_fns index into).
        return {"prices": await self.client.prices()}
