"""Diagnostics for the Mempool integration.

Diagnostics downloads get pasted into public issue reports, so this module
treats the output as public. For a self-hosted user the instance URL is
typically an internal hostname, so it — and everything else derived from it —
is redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_URL, MEMPOOL_SPACE_URL
from .coordinator import MempoolConfigEntry

# The base URL is the only user-identifying value the entry stores. It is also
# the config entry's unique_id, and the entry title is derived from its host,
# so all three have to go rather than just the one key.
TO_REDACT = {CONF_BASE_URL}


def _describe_instance(base_url: str) -> str:
    """Say which kind of instance this is without naming it.

    The public instance is not a secret and knowing which one is in use is the
    single most useful fact when reading a bug report, so it is named. Anything
    else is a self-hosted address and stays redacted.
    """
    return "mempool.space (public)" if base_url == MEMPOOL_SPACE_URL else "self-hosted"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MempoolConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    base_url = entry.data[CONF_BASE_URL]

    return {
        "instance": _describe_instance(base_url),
        # Redacted, then the title and unique_id are omitted entirely rather
        # than redacted, since both embed the host.
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "version": entry.version,
            "source": entry.source,
        },
        "currency": data.currency,
        "price_attributes_enabled": data.price_attributes,
        "price_feed_available": data.price is not None,
        # Coordinator payloads are public blockchain data: chain tip, fees,
        # mempool summary, difficulty, mining pools and spot price. None of it
        # is specific to this user or their instance.
        "coordinators": {
            name: {
                "last_update_success": coordinator.last_update_success,
                "update_interval": (
                    coordinator.update_interval.total_seconds()
                    if coordinator.update_interval
                    else None
                ),
                "data": coordinator.data,
            }
            for name, coordinator in (
                ("fast", data.fast),
                ("slow", data.slow),
                ("price", data.price),
            )
            if coordinator is not None
        },
    }
