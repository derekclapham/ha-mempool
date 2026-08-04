"""Services for the Mempool integration.

`mempool.import_price_history` backfills Home Assistant long-term statistics for
an entry's price sensor from the node's historical-price feed, so price charts
are rich immediately instead of filling in over time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    CONF_CURRENCY,
    DOMAIN,
    SERVICE_IMPORT_PRICE_HISTORY,
)

if TYPE_CHECKING:
    from .coordinator import MempoolConfigEntry

_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services once (idempotent across config entries)."""
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_PRICE_HISTORY):
        return

    async def _import_price_history(call: ServiceCall) -> None:
        await _handle_import_price_history(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_PRICE_HISTORY, _import_price_history, schema=_SCHEMA
    )


async def _handle_import_price_history(hass: HomeAssistant, call: ServiceCall) -> None:
    """Fetch historical price and import it as long-term statistics."""
    # Imported lazily: the recorder is only an after_dependency, so these
    # modules may not be needed (or present) until this service is actually run.
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import async_import_statistics

    # Resolve and sanity-check the target entry.
    entry_id: str = call.data[ATTR_CONFIG_ENTRY_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"Unknown mempool config entry: {entry_id}")

    if getattr(entry, "runtime_data", None) is None:
        raise ServiceValidationError("The mempool entry is not loaded.")

    entry = _typed(entry)
    currency: str | None = entry.data.get(CONF_CURRENCY)
    if not currency:
        raise ServiceValidationError("This entry has no price currency configured.")

    # Statistics are keyed by the entity_id, so resolve it from the price
    # sensor's unique_id (which encodes the entry + currency, see sensor.py).
    registry = er.async_get(hass)
    unique_id = f"{entry_id}_price_{currency.lower()}"
    statistic_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if statistic_id is None:
        raise ServiceValidationError(
            "Price sensor not found — is the price feed enabled on the node?"
        )

    client = entry.runtime_data.client
    try:
        raw = await client.historical_price(currency)
    except Exception as err:  # noqa: BLE001 - surfaced to the user
        raise HomeAssistantError(f"Failed to fetch historical price: {err}") from err

    # The feed is {"prices": [...]}; tolerate a bare list just in case.
    points = raw.get("prices", raw) if isinstance(raw, dict) else raw
    stats = _to_hourly_stats(points, currency, StatisticData)
    if not stats:
        raise HomeAssistantError("Historical price feed returned no usable data.")

    # source="recorder" + a plain entity_id imports into that entity's own
    # long-term stats (an upsert per hour), so re-running is safe. has_mean
    # (not has_sum) because a price is an average, not a running total.
    metadata = StatisticMetaData(
        has_mean=True,
        has_sum=False,
        name=None,
        source="recorder",
        statistic_id=statistic_id,
        unit_of_measurement=currency,
    )
    async_import_statistics(hass, metadata, stats)


def _to_hourly_stats(
    points: list[dict[str, Any]], currency: str, statistic_data: Any
) -> list[Any]:
    """Turn raw price points into hourly StatisticData rows.

    Long-term statistics are hourly, so each point is floored to its hour.
    We drop unparsable rows and non-positive placeholders (older mempool feeds
    emit -1 for a fiat before that pair existed), and let a later point win
    within the same hour (`by_hour` overwrites). One value per hour means
    mean == min == max.
    """
    by_hour: dict[int, float] = {}
    for p in points or []:
        try:
            value = float(p[currency])
            ts = int(p["time"])
        except (KeyError, TypeError, ValueError):
            continue
        if value <= 0:
            continue
        by_hour[(ts // 3600) * 3600] = value  # floor epoch seconds to the hour

    stats: list[Any] = []
    for hour in sorted(by_hour):  # HA expects rows in ascending start order
        value = by_hour[hour]
        stats.append(
            statistic_data(
                start=dt_util.utc_from_timestamp(hour),  # tz-aware, hour-aligned
                mean=value,
                min=value,
                max=value,
            )
        )
    return stats


def _typed(entry: Any) -> MempoolConfigEntry:
    """Narrow a ConfigEntry to the integration's typed entry (for the checker)."""
    return entry
