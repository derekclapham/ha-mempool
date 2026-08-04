"""The Mempool (self-hosted Bitcoin node) integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MempoolApiError, MempoolClient
from .const import (
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    CONF_PRICE_ATTRIBUTES,
    CONF_VERIFY_SSL,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_VERIFY_SSL,
    LOGGER,
    PLATFORMS,
)
from .coordinator import (
    MempoolConfigEntry,
    MempoolData,
    MempoolFastCoordinator,
    MempoolPriceCoordinator,
    MempoolSlowCoordinator,
)
from .services import async_setup_services


async def async_setup_entry(hass: HomeAssistant, entry: MempoolConfigEntry) -> bool:
    """Set up Mempool from a config entry.

    Builds the client and coordinators, primes them once, stashes everything on
    `entry.runtime_data`, then forwards to the sensor platform.
    """
    # Options (set via the Configure dialog) win over the values captured at
    # setup; fall back to the defaults if neither is present. verify_ssl,
    # currency and the fast interval are all editable after setup.
    verify_ssl: bool = entry.options.get(
        CONF_VERIFY_SSL, entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    )
    currency: str | None = entry.options.get(
        CONF_CURRENCY, entry.data.get(CONF_CURRENCY)
    )
    price_attributes: bool = entry.options.get(
        CONF_PRICE_ATTRIBUTES, entry.data.get(CONF_PRICE_ATTRIBUTES, False)
    )
    fast_interval = timedelta(
        seconds=entry.options.get(
            CONF_FAST_INTERVAL,
            entry.data.get(CONF_FAST_INTERVAL, DEFAULT_FAST_INTERVAL),
        )
    )

    # Reuse HA's shared aiohttp session (verify or non-verify variant) rather
    # than owning a connection.
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = MempoolClient(session, entry.data[CONF_BASE_URL])

    fast = MempoolFastCoordinator(hass, entry, client, fast_interval)
    slow = MempoolSlowCoordinator(hass, entry, client)

    # The price feed is optional on self-hosted instances — only wire up the
    # price coordinator (and its sensor) when the endpoint actually responds
    # with our currency. A missing feed is a warning, not a setup failure.
    price: MempoolPriceCoordinator | None = None
    if currency:
        try:
            sample = await client.prices()
        except MempoolApiError:
            sample = None
        if isinstance(sample, dict) and currency in sample:
            price = MempoolPriceCoordinator(hass, entry, client)
        else:
            LOGGER.warning(
                "Price feed unavailable or missing %s at %s; price sensor disabled",
                currency,
                client.base_url,
            )

    # First refresh before creating entities so they start with real values;
    # if the node is unreachable this raises ConfigEntryNotReady and HA retries.
    await fast.async_config_entry_first_refresh()
    await slow.async_config_entry_first_refresh()
    if price is not None:
        await price.async_config_entry_first_refresh()

    entry.runtime_data = MempoolData(
        client, currency, price_attributes, fast, slow, price
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload (rebuilding coordinators with the new interval) when options change.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    # Services are global, not per-entry; async_setup_services is idempotent.
    async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MempoolConfigEntry) -> bool:
    """Unload a config entry (tear down its platforms and coordinators)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: MempoolConfigEntry) -> None:
    """Reload the entry when its options change (e.g. a new poll interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
