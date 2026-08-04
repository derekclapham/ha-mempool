"""Sensor platform for the Mempool integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import MempoolConfigEntry

# Read-only sensors backed by coordinators; nothing to serialise on update.
PARALLEL_UPDATES = 0


# --- small helpers used by the value_fn lambdas -------------------------------
# Each pulls a field out of the relevant coordinator payload sub-dict and is
# defensive: a partial/early payload yields None (which marks the sensor
# unavailable) rather than raising.


def _num(value: Any) -> float | None:
    """Coerce to float, or None if absent/unparsable."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fee(data: dict[str, Any], key: str) -> StateType:
    """Read a field from the recommended-fees sub-dict."""
    return (data.get("fees") or {}).get(key)


def _mp(data: dict[str, Any], key: str) -> Any:
    """Read a field from the mempool-summary sub-dict."""
    return (data.get("mempool") or {}).get(key)


def _diff(data: dict[str, Any], key: str) -> Any:
    """Read a field from the difficulty-adjustment sub-dict."""
    return (data.get("difficulty") or {}).get(key)


def _hash(data: dict[str, Any], key: str) -> Any:
    """Read a field from the hashrate sub-dict."""
    return (data.get("hashrate") or {}).get(key)


def _retarget(data: dict[str, Any]) -> datetime | None:
    """Convert the retarget epoch (ms) into a tz-aware datetime for HA."""
    ms = _num(_diff(data, "estimatedRetargetDate"))
    return dt_util.utc_from_timestamp(ms / 1000) if ms else None


def _scaled(value: Any, factor: float) -> float | None:
    """Divide a raw value by `factor` (e.g. sats→BTC), or None if missing."""
    v = _num(value)
    return v / factor if v is not None else None


@dataclass(frozen=True, kw_only=True)
class MempoolSensorDescription(SensorEntityDescription):
    """Describes a Mempool sensor and where its value comes from.

    Extends the standard description with two fields:
      * `group`     — which coordinator ("fast" | "slow" | "price") backs it.
      * `value_fn`  — extracts the state from that coordinator's payload,
                      given (payload_dict, currency).
    """

    group: str
    value_fn: Callable[[dict[str, Any], str | None], StateType | datetime]
    # Default integer sensors (block height, fees, counts) to whole numbers so
    # their history-graph axes don't render interpolated decimal ticks. Sensors
    # with fractional units override this below; the timestamp sensor ignores it.
    suggested_display_precision: int | None = 0


# The non-price sensors, in display order. `suggested_display_precision` only
# rounds the UI — the recorded state keeps full precision for statistics.
SENSORS: tuple[MempoolSensorDescription, ...] = (
    # ---- fast group (chain tip, fees, mempool) ----
    MempoolSensorDescription(
        key="block_height",
        translation_key="block_height",
        icon="mdi:cube-outline",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: d.get("height"),
    ),
    MempoolSensorDescription(
        key="fee_fastest",
        translation_key="fee_fastest",
        icon="mdi:rocket-launch-outline",
        native_unit_of_measurement="sat/vB",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _fee(d, "fastestFee"),
    ),
    MempoolSensorDescription(
        key="fee_half_hour",
        translation_key="fee_half_hour",
        icon="mdi:clock-fast",
        native_unit_of_measurement="sat/vB",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _fee(d, "halfHourFee"),
    ),
    MempoolSensorDescription(
        key="fee_hour",
        translation_key="fee_hour",
        icon="mdi:clock-outline",
        native_unit_of_measurement="sat/vB",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _fee(d, "hourFee"),
    ),
    MempoolSensorDescription(
        key="fee_economy",
        translation_key="fee_economy",
        icon="mdi:cash-minus",
        native_unit_of_measurement="sat/vB",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _fee(d, "economyFee"),
    ),
    MempoolSensorDescription(
        key="fee_minimum",
        translation_key="fee_minimum",
        icon="mdi:cash-remove",
        native_unit_of_measurement="sat/vB",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _fee(d, "minimumFee"),
    ),
    MempoolSensorDescription(
        key="mempool_transactions",
        translation_key="mempool_transactions",
        icon="mdi:file-tree-outline",
        native_unit_of_measurement="tx",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _mp(d, "count"),
    ),
    MempoolSensorDescription(
        key="mempool_size",
        translation_key="mempool_size",
        icon="mdi:database-outline",
        native_unit_of_measurement="MvB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        group="fast",
        # vsize is in vB; show millions of vB (MvB).
        value_fn=lambda d, _c: _scaled(_mp(d, "vsize"), 1_000_000),
    ),
    MempoolSensorDescription(
        key="mempool_total_fees",
        translation_key="mempool_total_fees",
        icon="mdi:cash-multiple",
        native_unit_of_measurement="BTC",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        group="fast",
        # total_fee is in satoshis; 1 BTC = 100,000,000 sats.
        value_fn=lambda d, _c: _scaled(_mp(d, "total_fee"), 100_000_000),
    ),
    # ---- slow group (difficulty adjustment, mining) ----
    MempoolSensorDescription(
        key="difficulty_progress",
        translation_key="difficulty_progress",
        icon="mdi:progress-clock",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        group="slow",
        value_fn=lambda d, _c: _diff(d, "progressPercent"),
    ),
    MempoolSensorDescription(
        key="difficulty_change",
        translation_key="difficulty_change",
        icon="mdi:swap-vertical-bold",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        group="slow",
        value_fn=lambda d, _c: _diff(d, "difficultyChange"),
    ),
    MempoolSensorDescription(
        key="blocks_to_retarget",
        translation_key="blocks_to_retarget",
        icon="mdi:cube-scan",
        native_unit_of_measurement="blocks",
        state_class=SensorStateClass.MEASUREMENT,
        group="slow",
        value_fn=lambda d, _c: _diff(d, "remainingBlocks"),
    ),
    MempoolSensorDescription(
        key="next_retarget",
        translation_key="next_retarget",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        group="slow",
        value_fn=lambda d, _c: _retarget(d),
    ),
    MempoolSensorDescription(
        key="hashrate",
        translation_key="hashrate",
        icon="mdi:speedometer",
        native_unit_of_measurement="EH/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        group="slow",
        # currentHashrate is in H/s; 1 EH/s = 1e18 H/s.
        value_fn=lambda d, _c: _scaled(_hash(d, "currentHashrate"), 1e18),
    ),
    MempoolSensorDescription(
        key="difficulty",
        translation_key="difficulty",
        icon="mdi:chart-line-variant",
        native_unit_of_measurement="T",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        group="slow",
        # Difficulty is a huge dimensionless number; show trillions (T).
        value_fn=lambda d, _c: _scaled(_hash(d, "currentDifficulty"), 1e12),
    ),
)

# Defined separately because it only exists when a price feed is present, and
# its unit/value depend on the chosen currency (resolved on the entity).
PRICE_SENSOR = MempoolSensorDescription(
    key="price",
    translation_key="price",
    icon="mdi:bitcoin",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=0,
    group="price",
    value_fn=lambda d, c: (d.get("prices") or {}).get(c) if c else None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MempoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one sensor per description, wired to the right coordinator."""
    data = entry.runtime_data
    coordinators = {"fast": data.fast, "slow": data.slow, "price": data.price}

    entities = [
        MempoolSensor(coordinators[desc.group], entry, desc, data.currency)
        for desc in SENSORS
    ]
    # Add the price sensor only when a price coordinator was created.
    if data.price is not None and data.currency:
        entities.append(
            MempoolSensor(data.price, entry, PRICE_SENSOR, data.currency)
        )
    async_add_entities(entities)


class MempoolSensor(CoordinatorEntity, SensorEntity):
    """A single value derived from a coordinator's payload."""

    _attr_has_entity_name = True
    entity_description: MempoolSensorDescription

    def __init__(
        self,
        coordinator: Any,
        entry: MempoolConfigEntry,
        description: MempoolSensorDescription,
        currency: str | None,
    ) -> None:
        """Bind the sensor to its coordinator and config entry."""
        super().__init__(coordinator)
        self.entity_description = description
        self._currency = currency
        # The price sensor's unique_id carries the currency so switching fiats
        # yields a distinct statistic rather than mixing units in one series.
        self._attr_unique_id = (
            f"{entry.entry_id}_{description.key}"
            if description.key != "price"
            else f"{entry.entry_id}_price_{(currency or '').lower()}"
        )
        # Price unit is per-entry (the chosen fiat), so it's set here rather
        # than statically on the description.
        if description.key == "price" and currency:
            self._attr_native_unit_of_measurement = currency
        # One device per config entry (the node); all sensors group under it.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="mempool",
            model="Self-hosted mempool",
            configuration_url=entry.data[CONF_BASE_URL],
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value by applying the description's value_fn."""
        return self.entity_description.value_fn(
            self.coordinator.data or {}, self._currency
        )

    @property
    def available(self) -> bool:
        """Available only when the last poll worked and a value is present.

        `super().available` covers coordinator success; the extra check hides a
        sensor whose specific field is missing from an otherwise-good payload.
        """
        return super().available and self.native_value is not None
