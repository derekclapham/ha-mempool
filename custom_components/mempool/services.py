"""Services for the Mempool integration.

`mempool.import_price_history` backfills Home Assistant long-term statistics for
an entry's price sensor from the node's historical-price feed, so price charts
are rich immediately instead of filling in over time.
"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    CONF_CURRENCY,
    DOMAIN,
    LOGGER,
    MAX_STATISTICS_ROWS,
    SERVICE_IMPORT_PRICE_HISTORY,
)

if TYPE_CHECKING:
    from .coordinator import MempoolConfigEntry

_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions.

    Called once from `async_setup`, so no per-entry idempotency guard is needed.
    """

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
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )

    # The action can be called while no entry is loaded, so check the state
    # rather than assuming runtime_data is populated.
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_not_loaded"
        )

    entry = _typed(entry)
    # Options win over the setup-time data (the currency can be changed later).
    currency: str | None = entry.options.get(
        CONF_CURRENCY, entry.data.get(CONF_CURRENCY)
    )
    if not currency:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_currency"
        )

    # Statistics are keyed by the entity_id, so resolve it from the price
    # sensor's unique_id (which encodes the entry + currency, see sensor.py).
    registry = er.async_get(hass)
    unique_id = f"{entry_id}_price_{currency.lower()}"
    statistic_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if statistic_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="price_sensor_missing"
        )

    client = entry.runtime_data.client
    try:
        raw = await client.historical_price(currency)
    # Deliberately broad: whatever the client raises is re-raised as a
    # HomeAssistantError so the user sees it rather than a traceback.
    except Exception as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="historical_fetch_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    # The feed is {"prices": [...]}; tolerate a bare list just in case.
    points = raw.get("prices", raw) if isinstance(raw, dict) else raw
    stats = _to_hourly_stats(points, currency, StatisticData)
    if not stats:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="no_usable_history"
        )

    # source="recorder" + a plain entity_id imports into that entity's own
    # long-term stats (an upsert per hour), so re-running is safe. has_mean
    # (not has_sum) because a price is an average, not a running total.
    #
    # `has_mean` is deprecated in newer Home Assistant in favour of `mean_type`,
    # which arrived alongside `unit_class` and does not exist at the version
    # declared in hacs.json. Setting either would break the declared minimum,
    # so this keeps the older spelling: the recorder has an explicit shim for
    # exactly this case, deriving mean_type from has_mean (True -> ARITHMETIC)
    # and unit_class from the unit (a currency has no converter, so None). When
    # the minimum rises past the release that drops has_mean, swap this for
    # mean_type=StatisticMeanType.ARITHMETIC and unit_class=None.
    metadata = StatisticMetaData(  # type: ignore[typeddict-item]
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
        if len(by_hour) >= MAX_STATISTICS_ROWS:
            # Each row becomes a durable statistics record, and the instance
            # decides how many points it sends. Hourly points for the whole of
            # Bitcoin's existence is a small fraction of this ceiling.
            LOGGER.warning(
                "Historical price feed returned more than %s hourly points; "
                "importing the first %s",
                MAX_STATISTICS_ROWS,
                MAX_STATISTICS_ROWS,
            )
            break
        try:
            value = float(p[currency])
            ts = int(p["time"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if value <= 0 or not isfinite(value):
            continue
        by_hour[(ts // 3600) * 3600] = value  # floor epoch seconds to the hour

    stats: list[Any] = []
    for hour in sorted(by_hour):  # HA expects rows in ascending start order
        value = by_hour[hour]
        try:
            start = dt_util.utc_from_timestamp(hour)  # tz-aware, hour-aligned
        except (OSError, OverflowError, ValueError):
            # An epoch the platform cannot represent. Skip the row rather than
            # failing an import whose other rows are perfectly good.
            continue
        stats.append(
            statistic_data(start=start, mean=value, min=value, max=value)
        )
    return stats


def _typed(entry: ConfigEntry) -> MempoolConfigEntry:
    """Narrow a ConfigEntry to the integration's typed entry (for the checker).

    The domain and loaded-state checks above have already established that this
    entry is ours and has its runtime_data populated, which is what the cast
    asserts and the type system cannot see.
    """
    return cast("MempoolConfigEntry", entry)
