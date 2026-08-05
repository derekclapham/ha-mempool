"""Tests for the `mempool.import_price_history` action."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.const import (
    API_HISTORICAL_PRICE,
    ATTR_CONFIG_ENTRY_ID,
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    CONF_VERIFY_SSL,
    DOMAIN,
    SERVICE_IMPORT_PRICE_HISTORY,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import BASE_URL, NOW_TS, mock_endpoints

IMPORT_TARGET = (
    "homeassistant.components.recorder.statistics.async_import_statistics"
)


async def _call(hass: HomeAssistant, entry_id: str) -> None:
    """Invoke the action for one config entry."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_IMPORT_PRICE_HISTORY,
        {ATTR_CONFIG_ENTRY_ID: entry_id},
        blocking=True,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up an entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_import_price_history(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The happy path imports one hourly row per price point."""
    await _setup(hass, mock_config_entry)

    with patch(IMPORT_TARGET) as mock_import:
        await _call(hass, mock_config_entry.entry_id)

    assert mock_import.call_count == 1
    _hass_arg, metadata, stats = mock_import.call_args[0]

    assert metadata["source"] == "recorder"
    assert metadata["unit_of_measurement"] == "USD"
    assert metadata["has_mean"] is True
    assert metadata["has_sum"] is False
    # Statistics are keyed by entity_id, resolved from the price sensor.
    assert metadata["statistic_id"].startswith("sensor.")

    assert len(stats) == 3
    assert [row["mean"] for row in stats] == [94000, 94500, 95000]
    # Rows must be in ascending start order and hour-aligned.
    starts = [row["start"] for row in stats]
    assert starts == sorted(starts)
    assert all(start.minute == 0 and start.second == 0 for start in starts)
    # One value per hour means mean == min == max.
    assert all(row["mean"] == row["min"] == row["max"] for row in stats)


async def test_import_is_idempotent_shape(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-running produces the identical row set (the import is an upsert)."""
    await _setup(hass, mock_config_entry)

    with patch(IMPORT_TARGET) as mock_import:
        await _call(hass, mock_config_entry.entry_id)
        await _call(hass, mock_config_entry.entry_id)

    first, second = (call[0][2] for call in mock_import.call_args_list)
    assert first == second


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        # Two points in one hour: the later one wins.
        (
            [
                {"time": NOW_TS, "USD": 100},
                {"time": NOW_TS + 60, "USD": 200},
            ],
            [200],
        ),
        # -1 is the placeholder older feeds emit before a pair existed.
        ([{"time": NOW_TS, "USD": -1}, {"time": NOW_TS + 3600, "USD": 300}], [300]),
        # Rows missing the currency or the timestamp are skipped.
        (
            [
                {"time": NOW_TS},
                {"USD": 400},
                {"time": "not-a-time", "USD": 500},
                {"time": NOW_TS + 3600, "USD": 600},
            ],
            [600],
        ),
    ],
)
async def test_import_filters_bad_points(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    points: list[dict[str, Any]],
    expected: list[float],
) -> None:
    """Unusable price points are dropped rather than failing the import."""
    mock_endpoints(
        aioclient_mock,
        overrides={API_HISTORICAL_PRICE: {"json": {"prices": points}}},
    )

    await _setup(hass, mock_config_entry)
    with patch(IMPORT_TARGET) as mock_import:
        await _call(hass, mock_config_entry.entry_id)

    stats = mock_import.call_args[0][2]
    assert [row["mean"] for row in stats] == expected


async def test_import_accepts_bare_list(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A feed that returns a bare list instead of {"prices": [...]} still works."""
    mock_endpoints(
        aioclient_mock,
        overrides={API_HISTORICAL_PRICE: {"json": [{"time": NOW_TS, "USD": 123}]}},
    )

    await _setup(hass, mock_config_entry)
    with patch(IMPORT_TARGET) as mock_import:
        await _call(hass, mock_config_entry.entry_id)

    assert mock_import.call_args[0][2][0]["mean"] == 123


# --- failure modes ------------------------------------------------------------


async def test_unknown_entry(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An entry_id that is not ours is rejected."""
    await _setup(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await _call(hass, "does-not-exist")


async def test_entry_not_loaded(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A config entry that is not currently loaded is rejected."""
    await _setup(hass, mock_config_entry)

    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://other.test",
        data={CONF_BASE_URL: "http://other.test"},
    )
    other.add_to_hass(hass)

    with pytest.raises(ServiceValidationError):
        await _call(hass, other.entry_id)


async def test_entry_without_currency(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
) -> None:
    """An entry with no price currency has nothing to import."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=BASE_URL,
        data={
            CONF_BASE_URL: BASE_URL,
            CONF_VERIFY_SSL: True,
            CONF_FAST_INTERVAL: 60,
        },
    )
    await _setup(hass, entry)

    with pytest.raises(ServiceValidationError):
        await _call(hass, entry.entry_id)


async def test_price_sensor_missing(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A currency is configured but the instance serves no price feed."""
    await _setup(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await _call(hass, mock_config_entry.entry_id)


async def test_fetch_failure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failing historical-price fetch surfaces as a HomeAssistantError."""
    mock_endpoints(
        aioclient_mock,
        overrides={API_HISTORICAL_PRICE: {"status": 500}},
    )

    await _setup(hass, mock_config_entry)

    # A failing upstream is the service malfunctioning, not the user getting
    # the call wrong, so it must be HomeAssistantError and specifically not
    # ServiceValidationError -- which subclasses it and would pass a looser
    # assertion.
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, mock_config_entry.entry_id)
    assert not isinstance(err.value, ServiceValidationError)


async def test_empty_feed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A feed with no usable rows is an error, not a silent no-op."""
    mock_endpoints(
        aioclient_mock,
        overrides={API_HISTORICAL_PRICE: {"json": {"prices": []}}},
    )

    await _setup(hass, mock_config_entry)

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, mock_config_entry.entry_id)
    assert not isinstance(err.value, ServiceValidationError)


async def test_uses_options_currency(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The currency chosen in options wins over the one captured at setup."""
    mock_endpoints(
        aioclient_mock,
        overrides={
            API_HISTORICAL_PRICE: {
                "json": {"prices": [{"time": NOW_TS, "AUD": 145000}]}
            }
        },
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_CURRENCY: "AUD"}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with patch(IMPORT_TARGET) as mock_import:
        await _call(hass, mock_config_entry.entry_id)

    metadata = mock_import.call_args[0][1]
    assert metadata["unit_of_measurement"] == "AUD"
    assert mock_import.call_args[0][2][0]["start"] == dt_util.utc_from_timestamp(
        NOW_TS
    )


async def test_entry_loaded_then_unloaded(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An entry that was loaded and then unloaded is rejected.

    Distinct from test_entry_not_loaded, which never loads at all. Home
    Assistant clears runtime_data on unload, so both the old presence check
    and the current ConfigEntryState.LOADED check reject this; the state
    check is simply the one the action-setup rule prescribes.
    """
    await _setup(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED

    with pytest.raises(ServiceValidationError):
        await _call(hass, mock_config_entry.entry_id)


async def test_import_reaches_the_real_recorder(
    recorder_mock: Any,
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Drive the import through the real recorder, not a patched function.

    Every other test here patches async_import_statistics, which would hide a
    metadata dict the recorder rejects. That matters because `has_mean` is
    deprecated in favour of `mean_type`: this integration still sends the older
    spelling so it keeps working at its declared minimum Home Assistant
    version, and this test is what proves the recorder's compatibility shim
    still accepts it on the version actually installed.
    """
    from homeassistant.components.recorder.statistics import statistics_during_period
    from homeassistant.components.recorder.util import get_instance

    await _setup(hass, mock_config_entry)

    registry = er.async_get(hass)
    statistic_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_price_usd"
    )
    assert statistic_id is not None

    await _call(hass, mock_config_entry.entry_id)
    await async_wait_recording_done(hass)

    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(NOW_TS - 86400),
        None,
        {statistic_id},
        "hour",
        None,
        {"mean", "min", "max"},
    )

    rows = stats[statistic_id]
    assert [row["mean"] for row in rows] == [94000, 94500, 95000]
