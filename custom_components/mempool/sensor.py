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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import HALVING_INTERVAL, INITIAL_SUBSIDY
from .coordinator import MempoolConfigEntry
from .entity import MempoolEntity

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


def _block(data: dict[str, Any], key: str) -> Any:
    """Read a top-level field from the chain-tip block (blocks[0])."""
    blocks = data.get("blocks") or []
    return blocks[0].get(key) if blocks else None


def _block_extra(data: dict[str, Any], key: str) -> Any:
    """Read a field from the tip block's `extras` object."""
    blocks = data.get("blocks") or []
    return (blocks[0].get("extras") or {}).get(key) if blocks else None


def _block_time(data: dict[str, Any]) -> datetime | None:
    """Tip block's timestamp as a tz-aware datetime (renders as 'x ago')."""
    ts = _num(_block(data, "timestamp"))
    return dt_util.utc_from_timestamp(ts) if ts else None


def _block_pool(data: dict[str, Any]) -> StateType:
    """Name of the pool that mined the tip block."""
    return (_block_extra(data, "pool") or {}).get("name")


def _subsidy(height: Any) -> float | None:
    """Current block subsidy in BTC, halving every 210k blocks."""
    h = _num(height)
    return INITIAL_SUBSIDY / (2 ** (int(h) // HALVING_INTERVAL)) if h else None


def _blocks_to_halving(height: Any) -> int | None:
    """Blocks remaining until the next subsidy halving."""
    h = _num(height)
    return HALVING_INTERVAL - (int(h) % HALVING_INTERVAL) if h else None


def _next_halving_time(data: dict[str, Any]) -> datetime | None:
    """Estimated datetime of the next halving.

    Anchored to the current tip block's timestamp plus the remaining blocks at
    Bitcoin's 10-minute (600 s) target — so it stays stable between blocks
    rather than drifting every poll, and only nudges when a new block lands.
    """
    height = _num(data.get("height"))
    anchor = _num(_block(data, "timestamp"))
    if height is None or anchor is None:
        return None
    blocks_left = HALVING_INTERVAL - (int(height) % HALVING_INTERVAL)
    return dt_util.utc_from_timestamp(anchor + blocks_left * 600)


def _projected(data: dict[str, Any], index: int, key: str) -> Any:
    """Read a field from a projected mempool block by position."""
    proj = data.get("projected") or []
    return proj[index].get(key) if len(proj) > index else None


def _pools(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The mining-pool list from the last-week distribution."""
    return ((data.get("pools") or {}).get("pools")) or []


def _top_pool_share(data: dict[str, Any]) -> float | None:
    """Share (%) of blocks mined by the top pool over the window."""
    pools = _pools(data)
    if not pools:
        return None
    total = sum(_num(p.get("blockCount")) or 0 for p in pools)
    top = _num(pools[0].get("blockCount")) or 0
    return top / total * 100 if total else None


def _blocks_last_hour(data: dict[str, Any]) -> int | None:
    """Blocks whose timestamp falls within the last 60 minutes.

    Uses the recent-blocks list (capped at ~15), which comfortably covers an
    hour unless the network is producing >15 blocks/hour (effectively never).
    """
    blocks = data.get("blocks") or []
    if not blocks:
        return None
    cutoff = dt_util.utcnow().timestamp() - 3600
    return sum(1 for b in blocks if (_num(b.get("timestamp")) or 0) >= cutoff)


def _network_pace(data: dict[str, Any]) -> float | None:
    """Block-production rate vs the 6-blocks/hour target, as a percentage.

    100% means exactly on the 10-minute-per-block schedule; below is slow.
    """
    n = _blocks_last_hour(data)
    return n / 6 * 100 if n is not None else None


def _reward(data: dict[str, Any], key: str) -> Any:
    """Read a field from the 144-block reward-stats object (values are strings)."""
    return (data.get("rewards") or {}).get(key)


def _mean_tx_fee(data: dict[str, Any]) -> float | None:
    """Mean fee per transaction over the last 144 blocks, in satoshis."""
    fee = _num(_reward(data, "totalFee"))
    tx = _num(_reward(data, "totalTx"))
    return fee / tx if fee is not None and tx else None


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
    # ---- latest block ----
    MempoolSensorDescription(
        key="latest_block_time",
        translation_key="latest_block_time",
        icon="mdi:cube",
        device_class=SensorDeviceClass.TIMESTAMP,
        suggested_display_precision=None,  # datetime; renders as "x min ago"
        group="fast",
        value_fn=lambda d, _c: _block_time(d),
    ),
    MempoolSensorDescription(
        key="latest_block_transactions",
        translation_key="latest_block_transactions",
        icon="mdi:swap-horizontal",
        native_unit_of_measurement="tx",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _block(d, "tx_count"),
    ),
    MempoolSensorDescription(
        key="latest_block_size",
        translation_key="latest_block_size",
        icon="mdi:database",
        native_unit_of_measurement="MB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        group="fast",
        # block size is in bytes; show megabytes.
        value_fn=lambda d, _c: _scaled(_block(d, "size"), 1_000_000),
    ),
    MempoolSensorDescription(
        key="latest_block_weight",
        translation_key="latest_block_weight",
        icon="mdi:weight",
        native_unit_of_measurement="MWU",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        group="fast",
        # weight is in weight units; show millions (a full block is ~4 MWU).
        value_fn=lambda d, _c: _scaled(_block(d, "weight"), 1_000_000),
    ),
    MempoolSensorDescription(
        key="latest_block_miner",
        translation_key="latest_block_miner",
        icon="mdi:pickaxe",
        suggested_display_precision=None,  # string
        group="fast",
        value_fn=lambda d, _c: _block_pool(d),
    ),
    MempoolSensorDescription(
        key="latest_block_reward",
        translation_key="latest_block_reward",
        icon="mdi:cash-plus",
        native_unit_of_measurement="BTC",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        group="fast",
        # reward = subsidy + fees, in satoshis.
        value_fn=lambda d, _c: _scaled(_block_extra(d, "reward"), 100_000_000),
    ),
    MempoolSensorDescription(
        key="latest_block_fees",
        translation_key="latest_block_fees",
        icon="mdi:cash",
        native_unit_of_measurement="BTC",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        group="fast",
        value_fn=lambda d, _c: _scaled(_block_extra(d, "totalFees"), 100_000_000),
    ),
    MempoolSensorDescription(
        key="latest_block_median_fee",
        translation_key="latest_block_median_fee",
        icon="mdi:cash-clock",
        native_unit_of_measurement="sat/vB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        group="fast",
        value_fn=lambda d, _c: _block_extra(d, "medianFee"),
    ),
    # ---- mempool projection (next blocks) ----
    MempoolSensorDescription(
        key="projected_blocks",
        translation_key="projected_blocks",
        icon="mdi:layers-triple",
        native_unit_of_measurement="blocks",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        # how many blocks the current mempool would fill.
        value_fn=lambda d, _c: len(d.get("projected") or []),
    ),
    MempoolSensorDescription(
        key="next_block_fee",
        translation_key="next_block_fee",
        icon="mdi:cube-send",
        native_unit_of_measurement="sat/vB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        group="fast",
        value_fn=lambda d, _c: _projected(d, 0, "medianFee"),
    ),
    # ---- halving (computed from the chain tip height) ----
    MempoolSensorDescription(
        key="blocks_to_halving",
        translation_key="blocks_to_halving",
        icon="mdi:sync",
        native_unit_of_measurement="blocks",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _blocks_to_halving(d.get("height")),
    ),
    MempoolSensorDescription(
        key="block_subsidy",
        translation_key="block_subsidy",
        icon="mdi:bitcoin",
        native_unit_of_measurement="BTC",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        group="fast",
        value_fn=lambda d, _c: _subsidy(d.get("height")),
    ),
    MempoolSensorDescription(
        key="next_halving",
        translation_key="next_halving",
        icon="mdi:calendar-star",
        device_class=SensorDeviceClass.TIMESTAMP,
        suggested_display_precision=None,  # datetime; renders as a countdown
        group="fast",
        value_fn=lambda d, _c: _next_halving_time(d),
    ),
    # ---- block production rate (rolling 60 min) ----
    MempoolSensorDescription(
        key="blocks_per_hour",
        translation_key="blocks_per_hour",
        icon="mdi:timer-sand",
        native_unit_of_measurement="blocks/h",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        value_fn=lambda d, _c: _blocks_last_hour(d),
    ),
    MempoolSensorDescription(
        key="network_pace",
        translation_key="network_pace",
        icon="mdi:speedometer",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        group="fast",
        # 100% = on the 6-blocks/hour (10-min) schedule.
        value_fn=lambda d, _c: _network_pace(d),
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
        suggested_display_precision=None,  # precision is meaningless for a datetime
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
    # ---- mining pools (last week) ----
    MempoolSensorDescription(
        key="top_pool",
        translation_key="top_pool",
        icon="mdi:account-hard-hat",
        suggested_display_precision=None,  # string
        group="slow",
        value_fn=lambda d, _c: (_pools(d)[0].get("name") if _pools(d) else None),
    ),
    MempoolSensorDescription(
        key="top_pool_share",
        translation_key="top_pool_share",
        icon="mdi:chart-pie",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        group="slow",
        value_fn=lambda d, _c: _top_pool_share(d),
    ),
    # ---- mining reward stats (last ~24h / 144 blocks) ----
    MempoolSensorDescription(
        key="mining_reward_24h",
        translation_key="mining_reward_24h",
        icon="mdi:cash-plus",
        native_unit_of_measurement="BTC",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        group="slow",
        # totalReward (subsidy + fees) in satoshis over the last 144 blocks.
        value_fn=lambda d, _c: _scaled(_reward(d, "totalReward"), 100_000_000),
    ),
    MempoolSensorDescription(
        key="mining_fees_24h",
        translation_key="mining_fees_24h",
        icon="mdi:cash",
        native_unit_of_measurement="BTC",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        group="slow",
        value_fn=lambda d, _c: _scaled(_reward(d, "totalFee"), 100_000_000),
    ),
    MempoolSensorDescription(
        key="mean_tx_fee_24h",
        translation_key="mean_tx_fee_24h",
        icon="mdi:cash-clock",
        native_unit_of_measurement="sat",
        state_class=SensorStateClass.MEASUREMENT,
        group="slow",
        value_fn=lambda d, _c: _mean_tx_fee(d),
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
            MempoolSensor(
                data.price,
                entry,
                PRICE_SENSOR,
                data.currency,
                expose_currencies=data.price_attributes,
            )
        )
    async_add_entities(entities)


class MempoolSensor(MempoolEntity, SensorEntity):
    """A single value derived from a coordinator's payload."""

    entity_description: MempoolSensorDescription

    def __init__(
        self,
        coordinator: Any,
        entry: MempoolConfigEntry,
        description: MempoolSensorDescription,
        currency: str | None,
        expose_currencies: bool = False,
    ) -> None:
        """Bind the sensor to its coordinator and config entry."""
        # The price sensor's unique_id carries the currency so switching fiats
        # yields a distinct statistic rather than mixing units in one series.
        unique_suffix = (
            description.key
            if description.key != "price"
            else f"price_{(currency or '').lower()}"
        )
        super().__init__(coordinator, entry, unique_suffix)
        self.entity_description = description
        self._currency = currency
        # Only the price sensor, and only when the user opted in.
        self._expose_currencies = expose_currencies
        # Price unit is per-entry (the chosen fiat), so it's set here rather
        # than statically on the description.
        if description.key == "price" and currency:
            self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value by applying the description's value_fn.

        Returning None here yields `unknown`, which is deliberate. There is no
        `available` override: the quality scale draws a distinction between not
        being able to reach the instance at all — `unavailable`, which
        CoordinatorEntity already reports when a poll fails — and reaching it
        successfully but finding a particular field absent from the payload,
        which is `unknown`. Re-adding a `native_value is not None` check to
        `available` would collapse the second case into the first.
        """
        return self.entity_description.value_fn(
            self.coordinator.data or {}, self._currency
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Opt-in extra fiats on the price sensor (for templating, no stats).

        Attributes are not recorded as long-term statistics — they exist purely
        so automations/templates can read a currency other than the one chosen.
        """
        if not self._expose_currencies:
            return None
        prices = (self.coordinator.data or {}).get("prices") or {}
        return {
            code: value
            for code, value in prices.items()
            if code.isalpha()
            and len(code) == 3
            and code.isupper()
            and code != self._currency
        }
