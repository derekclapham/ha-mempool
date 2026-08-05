"""Tests for the Mempool sensor platform."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.const import (
    API_BLOCKS,
    API_MEMPOOL,
    API_MINING_POOLS,
    CONF_PRICE_ATTRIBUTES,
    DOMAIN,
)
from custom_components.mempool.sensor import PRICE_SENSOR, SENSORS
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import NOW, NOW_TS, TIP_HEIGHT, mock_endpoints


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, unique_suffix: str) -> str:
    """Resolve an entity_id from the unique_id suffix its description implies."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{unique_suffix}"
    )
    assert entity_id is not None, f"no entity for {unique_suffix}"
    return entity_id


def _state(hass: HomeAssistant, entry: MockConfigEntry, unique_suffix: str) -> str:
    """Current state string for a sensor identified by unique_id suffix."""
    return hass.states.get(_entity_id(hass, entry, unique_suffix)).state


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up an entry, waiting for the platform to settle."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# --- unique IDs ---------------------------------------------------------------


async def test_unique_ids_are_stable(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Lock the unique_id set down.

    Entity unique_ids are live in real installations and carry recorded history,
    so a change here silently orphans that history. This test exists to fail
    loudly if any `key=` or the unique_id composition is ever edited.
    """
    await _setup(hass, mock_config_entry)
    registry = er.async_get(hass)

    actual = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(
            registry, mock_config_entry.entry_id
        )
    }
    prefix = mock_config_entry.entry_id
    expected = {f"{prefix}_{description.key}" for description in SENSORS}
    # The price sensor carries the chosen fiat so switching starts a new series.
    expected.add(f"{prefix}_price_usd")

    assert actual == expected


async def test_expected_sensor_keys() -> None:
    """The described sensor set is fixed.

    35 described sensors, plus the price sensor when the instance has a feed,
    for 36 entities in total.
    """
    assert [description.key for description in SENSORS] == [
        "block_height",
        "fee_fastest",
        "fee_half_hour",
        "fee_hour",
        "fee_economy",
        "fee_minimum",
        "mempool_transactions",
        "mempool_size",
        "mempool_total_fees",
        "latest_block_time",
        "latest_block_transactions",
        "latest_block_size",
        "latest_block_weight",
        "latest_block_miner",
        "latest_block_reward",
        "latest_block_fees",
        "latest_block_median_fee",
        "projected_blocks",
        "next_block_fee",
        "blocks_to_halving",
        "block_subsidy",
        "next_halving",
        "blocks_per_hour",
        "network_pace",
        "difficulty_progress",
        "difficulty_change",
        "blocks_to_retarget",
        "next_retarget",
        "hashrate",
        "difficulty",
        "top_pool",
        "top_pool_share",
        "mining_reward_24h",
        "mining_fees_24h",
        "mean_tx_fee_24h",
    ]


# --- values -------------------------------------------------------------------

# Expected native values for the fixture payloads in conftest. Numeric entries
# are compared as floats; strings and timestamps are compared exactly.
EXPECTED: dict[str, Any] = {
    "block_height": 960953,
    "fee_fastest": 5,
    "fee_half_hour": 4,
    "fee_hour": 3,
    "fee_economy": 2,
    "fee_minimum": 1,
    "mempool_transactions": 12345,
    # 15,000,000 vB -> MvB
    "mempool_size": 15.0,
    # 50,000,000 sats -> BTC
    "mempool_total_fees": 0.5,
    "latest_block_transactions": 3200,
    # 1,500,000 bytes -> MB
    "latest_block_size": 1.5,
    # 3,990,000 WU -> MWU
    "latest_block_weight": 3.99,
    "latest_block_miner": "PoolAlpha",
    "latest_block_reward": 3.15,
    "latest_block_fees": 0.025,
    "latest_block_median_fee": 4.5,
    "projected_blocks": 3,
    "next_block_fee": 4.2,
    # 210,000 - (960,953 mod 210,000)
    "blocks_to_halving": 89047,
    # fifth subsidy epoch: 50 / 2**4
    "block_subsidy": 3.125,
    "difficulty_progress": 45.6,
    "difficulty_change": 2.34,
    "blocks_to_retarget": 1096,
    # 7.5e20 H/s -> EH/s
    "hashrate": 750.0,
    # 1.02e14 -> trillions
    "difficulty": 102.0,
    "top_pool": "PoolAlpha",
    # 300 of 600 blocks
    "top_pool_share": 50.0,
    "mining_reward_24h": 460.0,
    "mining_fees_24h": 6.0,
    # 600,000,000 sats over 400,000 transactions
    "mean_tx_fee_24h": 1500.0,
    "price_usd": 95000,
}


async def test_sensor_values(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    enable_all_entities: None,
) -> None:
    """Every sensor reports the value its payload implies."""
    freezer.move_to(NOW)
    await _setup(hass, mock_config_entry)

    for suffix, expected in EXPECTED.items():
        state = _state(hass, mock_config_entry, suffix)
        if isinstance(expected, str):
            assert state == expected, suffix
        else:
            assert float(state) == pytest.approx(expected), suffix


async def test_timestamp_sensors(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Timestamp sensors are tz-aware and anchored where they claim to be."""
    freezer.move_to(NOW)
    await _setup(hass, mock_config_entry)

    tip_time = NOW_TS - 300
    assert _state(hass, mock_config_entry, "latest_block_time") == (
        dt_util.utc_from_timestamp(tip_time).isoformat()
    )
    # The retarget estimate comes straight from the API, in milliseconds.
    assert _state(hass, mock_config_entry, "next_retarget") == (
        dt_util.utc_from_timestamp(1760000000).isoformat()
    )
    # The halving estimate is anchored to the tip block, not to "now", so it
    # stays put between polls: tip timestamp + remaining blocks * 600 s.
    assert _state(hass, mock_config_entry, "next_halving") == (
        dt_util.utc_from_timestamp(tip_time + 89047 * 600).isoformat()
    )


async def test_rolling_window_sensors(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    enable_all_entities: None,
) -> None:
    """Four of the five fixture blocks fall inside the trailing hour."""
    freezer.move_to(NOW)
    await _setup(hass, mock_config_entry)

    assert _state(hass, mock_config_entry, "blocks_per_hour") == "4"
    # 4 blocks against the 6-per-hour target.
    assert float(_state(hass, mock_config_entry, "network_pace")) == pytest.approx(
        4 / 6 * 100
    )


# --- availability -------------------------------------------------------------


async def test_sensor_unknown_when_field_missing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A field absent from an otherwise-healthy payload reads as unknown.

    Not unavailable: the instance answered, so it is reachable. Only the one
    value is missing. The paired test below covers the other half of that
    distinction, where the poll itself fails.
    """
    # A mempool summary that has `vsize` but no `count`.
    mock_endpoints(
        aioclient_mock,
        overrides={API_MEMPOOL: {"json": {"vsize": 15_000_000}}},
    )

    await _setup(hass, mock_config_entry)

    # count is gone, so mempool_transactions has no value to report...
    assert _state(hass, mock_config_entry, "mempool_transactions") == STATE_UNKNOWN
    # ...but vsize is still there, so its sibling is fine.
    assert _state(hass, mock_config_entry, "mempool_size") == "15.0"


async def test_sensors_unavailable_when_poll_fails(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failed refresh takes the whole coordinator's sensors unavailable."""
    await _setup(hass, mock_config_entry)
    assert _state(hass, mock_config_entry, "block_height") == str(TIP_HEIGHT)

    mock_config_entry.runtime_data.fast.async_set_update_error(
        Exception("node went away")
    )
    await hass.async_block_till_done()

    assert _state(hass, mock_config_entry, "block_height") == STATE_UNAVAILABLE
    # A different coordinator is unaffected.
    assert _state(hass, mock_config_entry, "hashrate") == "750.0"


async def test_empty_blocks_payload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An empty recent-blocks list leaves the block sensors unknown."""
    mock_endpoints(aioclient_mock, overrides={API_BLOCKS: {"json": []}})

    await _setup(hass, mock_config_entry)

    assert _state(hass, mock_config_entry, "latest_block_miner") == STATE_UNKNOWN
    assert _state(hass, mock_config_entry, "blocks_per_hour") == STATE_UNKNOWN
    # Height comes from its own endpoint and is unaffected.
    assert _state(hass, mock_config_entry, "block_height") == str(TIP_HEIGHT)


# --- price sensor -------------------------------------------------------------


async def test_price_sensor_absent_without_feed(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """With no price feed the price sensor is never created."""
    await _setup(hass, mock_config_entry)

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{mock_config_entry.entry_id}_price_usd"
        )
        is None
    )


async def test_price_attributes_opt_in(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Opting in attaches the other fiats, excluding the chosen one."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_PRICE_ATTRIBUTES: True}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, mock_config_entry, "price_usd"))
    assert state.attributes["EUR"] == 88000
    assert state.attributes["AUD"] == 145000
    assert "USD" not in state.attributes
    assert "time" not in state.attributes


async def test_price_attributes_off_by_default(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Without the opt-in no currency attributes are exposed."""
    await _setup(hass, mock_config_entry)

    state = hass.states.get(_entity_id(hass, mock_config_entry, "price_usd"))
    assert "EUR" not in state.attributes
    assert state.attributes["unit_of_measurement"] == "USD"


async def test_top_pool_sensors_with_no_pools(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    enable_all_entities: None,
) -> None:
    """An empty mining-pool list leaves both pool sensors unknown."""
    mock_endpoints(
        aioclient_mock, overrides={API_MINING_POOLS: {"json": {"pools": []}}}
    )

    await _setup(hass, mock_config_entry)

    assert _state(hass, mock_config_entry, "top_pool") == STATE_UNKNOWN
    assert _state(hass, mock_config_entry, "top_pool_share") == STATE_UNKNOWN


async def test_entity_naming_conventions(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Every entity has a unique ID, a translated name and has_entity_name."""
    await _setup(hass, mock_config_entry)
    registry = er.async_get(hass)

    entries = er.async_entries_for_config_entry(
        registry, mock_config_entry.entry_id
    )
    assert entries

    names = json.loads(
        (
            Path(__file__).parent.parent
            / "custom_components"
            / "mempool"
            / "strings.json"
        ).read_text()
    )["entity"]["sensor"]

    for entry in entries:
        assert entry.unique_id
        assert entry.has_entity_name
        assert entry.translation_key
        # The displayed name must actually resolve from strings.json. A key
        # with no matching entry leaves the entity nameless and collapses its
        # entity_id to the device name alone.
        assert entry.original_name == names[entry.translation_key]["name"]


async def test_unavailable_and_unknown_are_distinct(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The two states mean different things, and one sensor shows both.

    `unavailable` means the instance could not be reached; `unknown` means it
    answered but this particular field was absent. Asserting both on the same
    sensor is what stops a future `available` override from quietly collapsing
    the distinction, since either state alone would still look reasonable.
    """
    # Reachable, but the mempool summary omits `count`.
    mock_endpoints(
        aioclient_mock,
        overrides={API_MEMPOOL: {"json": {"vsize": 15_000_000}}},
    )
    await _setup(hass, mock_config_entry)

    assert _state(hass, mock_config_entry, "mempool_transactions") == STATE_UNKNOWN

    # Now the poll itself fails: the same sensor becomes unavailable.
    mock_config_entry.runtime_data.fast.async_set_update_error(
        Exception("instance unreachable")
    )
    await hass.async_block_till_done()

    assert (
        _state(hass, mock_config_entry, "mempool_transactions") == STATE_UNAVAILABLE
    )


# Sensors that ship switched off. One principle: keep the headline of each
# group, and disable restatements, obscure units and granular breakdowns.
# Everything here is either noisy (recomputed every poll) or narrow, and none
# of it is the only way to see something.
#
# Note what is deliberately NOT here. block_subsidy changes once every four
# years, so disabling it would save no recorder work at all while hiding a
# headline Bitcoin figure; and mining_reward_24h is the headline its two
# granular siblings break down. Listed explicitly because this only takes
# effect at first registration, making it invisible in ordinary use.
DISABLED_BY_DEFAULT = {
    "latest_block_median_fee",
    "latest_block_weight",
    "mean_tx_fee_24h",
    "mining_fees_24h",
    "network_pace",
    "projected_blocks",
    "top_pool_share",
}


async def test_disabled_by_default_set() -> None:
    """Exactly the intended sensors are disabled; the rest ship enabled."""
    actual = {
        description.key
        for description in (*SENSORS, PRICE_SENSOR)
        if not description.entity_registry_enabled_default
    }

    assert actual == DISABLED_BY_DEFAULT


async def test_disabled_sensors_are_registered_but_absent(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """They exist in the registry, switched off, with no state."""
    await _setup(hass, mock_config_entry)
    registry = er.async_get(hass)

    for key in DISABLED_BY_DEFAULT:
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{mock_config_entry.entry_id}_{key}"
        )
        assert entity_id is not None, key
        assert registry.async_get(entity_id).disabled_by is not None, key
        assert hass.states.get(entity_id) is None, key

    # The headline sensors are untouched.
    assert _state(hass, mock_config_entry, "block_height") == str(TIP_HEIGHT)
    assert _state(hass, mock_config_entry, "price_usd") == "95000"


async def test_block_size_has_a_device_class(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Block size is genuinely bytes, so it carries DATA_SIZE."""
    await _setup(hass, mock_config_entry)

    state = hass.states.get(_entity_id(hass, mock_config_entry, "latest_block_size"))
    assert state.attributes["device_class"] == SensorDeviceClass.DATA_SIZE
    assert state.attributes["unit_of_measurement"] == "MB"


async def test_price_sensor_has_no_device_class(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """MONETARY requires state_class TOTAL, which would change the statistics.

    The price sensor records a spot price as MEASUREMENT and already has
    history, so it stays untagged rather than being reinterpreted as a total.
    """
    assert PRICE_SENSOR.device_class is None
    assert PRICE_SENSOR.state_class is SensorStateClass.MEASUREMENT


async def test_no_sensor_has_an_entity_category() -> None:
    """Every sensor reports what the instance is *for*, so none is diagnostic."""
    for description in (*SENSORS, PRICE_SENSOR):
        assert description.entity_category is None, description.key
