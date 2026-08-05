"""The Mempool (self-hosted Bitcoin node) integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import MempoolApiError, MempoolClient
from .const import (
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    CONF_PRICE_ATTRIBUTES,
    CONF_VERIFY_SSL,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    LOGGER,
    MEMPOOL_SPACE_URL,
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

# Set up through the UI only; there is no YAML configuration for this domain.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's service actions.

    Actions are global rather than per-entry, and registering them here (not in
    async_setup_entry) means Home Assistant can validate automations that call
    them even while no entry is loaded.
    """
    async_setup_services(hass)
    return True


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
    _async_review_price_feed_issue(hass, entry, currency, feed_ok=price is not None)

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
    return True


def _price_feed_issue_id(entry: MempoolConfigEntry) -> str:
    """Repair issue ID for one entry's missing price feed."""
    return f"price_feed_unavailable_{entry.entry_id}"


@callback
def _async_review_price_feed_issue(
    hass: HomeAssistant,
    entry: MempoolConfigEntry,
    currency: str | None,
    *,
    feed_ok: bool,
) -> None:
    """Raise or clear the repair issue for a missing price feed.

    Evaluated on every setup, not only when the state changes, so the issue
    clears on the next reload once the user switches their feed on — and a
    reload already happens whenever options change.

    Deliberately limited to self-hosted instances. A repair issue is meant to
    be actionable, and a user can enable the price feed on their own node; if
    the public mempool.space price feed is down there is nothing they can do
    about it, so raising one there would be noise the rule warns against.
    """
    issue_id = _price_feed_issue_id(entry)
    is_public = entry.data[CONF_BASE_URL] == MEMPOOL_SPACE_URL

    if feed_ok or not currency or is_public:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="price_feed_unavailable",
        translation_placeholders={
            "title": entry.title,
            "currency": currency,
        },
    )


async def async_remove_entry(hass: HomeAssistant, entry: MempoolConfigEntry) -> None:
    """Clean up anything the entry owns outside its own runtime data."""
    ir.async_delete_issue(hass, DOMAIN, _price_feed_issue_id(entry))


async def async_unload_entry(hass: HomeAssistant, entry: MempoolConfigEntry) -> bool:
    """Unload a config entry (tear down its platforms and coordinators)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: MempoolConfigEntry) -> None:
    """Reload the entry when its options change (e.g. a new poll interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
