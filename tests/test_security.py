"""Regression tests for confirmed security findings.

Every test here replays a payload that demonstrably caused the bad outcome
before it was fixed, so a later refactor cannot quietly reopen it. Each names
the mechanism rather than just asserting the current behaviour, because the
behaviour is only interesting in light of what it prevents.

The threat model throughout: the mempool instance is untrusted. A compromised
instance, a hijacked DNS record, an intercepting proxy and a user who typed the
wrong address all deliver the same thing — attacker-chosen JSON to code running
inside the user's home.
"""

from __future__ import annotations

import itertools
import json
import signal
import string
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.api import MempoolApiError, MempoolClient
from custom_components.mempool.const import (
    API_BLOCKS,
    API_DIFFICULTY,
    API_MEMPOOL,
    API_MINING_POOLS,
    API_PRICES,
    API_TIP_HEIGHT,
    CONF_PRICE_ATTRIBUTES,
    DOMAIN,
    MAX_BLOCK_HEIGHT,
    MAX_CURRENCIES,
    MAX_LIST_ITEMS,
    MAX_STRING_LENGTH,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import BASE_URL, mock_endpoints


def _client(hass: HomeAssistant) -> MempoolClient:
    return MempoolClient(async_get_clientsession(hass), BASE_URL)


def _state(hass: HomeAssistant, entry: MockConfigEntry, suffix: str) -> Any:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    return hass.states.get(entity_id) if entity_id else None


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    entry.add_to_hass(hass)
    result = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return result


# --- unbounded work from a hostile chain tip ----------------------------------


async def test_hostile_block_height_does_not_hang_the_event_loop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A huge chain tip height must not freeze Home Assistant.

    The block subsidy halves every 210,000 blocks, so the height is used as an
    exponent. A height of 10^18 asks Python for 2**(4.76e12) — an integer
    needing hundreds of gigabytes — inside the event loop, during a state
    write. Before this was bounded, setup never returned.

    The alarm is the assertion: this test is meaningless if it merely passes
    slowly.
    """
    mock_endpoints(
        aioclient_mock, overrides={API_TIP_HEIGHT: {"text": "1" + "0" * 18}}
    )
    mock_config_entry.add_to_hass(hass)

    def _fail(*_args: object) -> None:
        raise TimeoutError("event loop blocked: the height bound is not working")

    signal.signal(signal.SIGALRM, _fail)
    signal.setitimer(signal.ITIMER_REAL, 10)
    try:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


@pytest.mark.parametrize(
    "height",
    [str(MAX_BLOCK_HEIGHT + 1), "-1", "1" + "0" * 30, "999999999999999999999"],
)
async def test_implausible_heights_are_refused_at_ingest(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, height: str
) -> None:
    """A height outside any believable range fails the poll cleanly."""
    mock_endpoints(aioclient_mock, overrides={API_TIP_HEIGHT: {"text": height}})

    with pytest.raises(MempoolApiError, match="Implausible chain tip height"):
        await _client(hass).tip_height()


async def test_plausible_heights_still_work(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The benign path: real heights, and the bound itself, are accepted.

    The hardening is only correct if it still lets ordinary values through.
    """
    for height in ("0", "1", "960953", str(MAX_BLOCK_HEIGHT)):
        aioclient_mock.clear_requests()
        mock_endpoints(aioclient_mock, overrides={API_TIP_HEIGHT: {"text": height}})
        assert await _client(hass).tip_height() == int(height)


# --- non-finite numbers -------------------------------------------------------


async def test_overflowing_literal_is_not_infinity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """`1e400` is a finite-looking literal that parses to infinity.

    Refusing the bare `Infinity` and `NaN` words is not enough on its own:
    Python's JSON parser turns an overflowing numeric literal into `inf`
    without ever consulting the constant hook. Demonstrated first, so the test
    rests on the parser's real behaviour rather than an assumption about it.
    """
    assert json.loads("1e400") == float("inf")

    aioclient_mock.get(
        f"{BASE_URL}{API_DIFFICULTY}", text='{"progressPercent": 1e400}'
    )

    with pytest.raises(MempoolApiError, match="Invalid JSON"):
        await _client(hass).difficulty_adjustment()


@pytest.mark.parametrize(
    "body",
    ['{"a": 1e400}', '{"a": -1e400}', "[1e999]", '{"a": {"b": 1e400}}'],
)
async def test_non_finite_numbers_refused_anywhere_in_the_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: str
) -> None:
    """Nesting does not smuggle a non-finite number past the check."""
    aioclient_mock.get(f"{BASE_URL}{API_DIFFICULTY}", text=body)

    with pytest.raises(MempoolApiError, match="Invalid JSON"):
        await _client(hass).difficulty_adjustment()


async def test_ordinary_floats_still_parse(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The benign path: normal numbers, including extremes, are untouched."""
    aioclient_mock.get(
        f"{BASE_URL}{API_DIFFICULTY}",
        text='{"progressPercent": 45.6, "tiny": 1e-300, "big": 1e308, "neg": -0.5}',
    )

    data = await _client(hass).difficulty_adjustment()

    assert data["progressPercent"] == 45.6
    assert data["big"] == 1e308
    assert data["neg"] == -0.5


# --- untrusted strings --------------------------------------------------------


async def test_control_characters_are_stripped_from_pool_names(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A pool name is chosen by the instance, not the user.

    Escape sequences rewrite the terminal of anyone tailing the log, newlines
    forge log entries, and a bidirectional override makes a name display as
    something other than what it is.
    """
    hostile = "\x1b[2Jwiped\r\nFAKE LOG LINE‮gnp\x00"
    mock_endpoints(
        aioclient_mock,
        overrides={
            API_MINING_POOLS: {
                "json": {"pools": [{"name": hostile, "blockCount": 5}]}
            }
        },
    )
    await _setup(hass, mock_config_entry)

    state = _state(hass, mock_config_entry, "top_pool").state

    # What matters is that nothing remains which a terminal, a log parser or a
    # text renderer will act on.
    for char in ("\x1b", "\r", "\n", "\x00", "‮"):
        assert char not in state
    # The printable remainder of a stripped escape sequence is left alone --
    # "[2J" without its introducer is just text, and inventing further rules
    # about which letters may follow a bracket would break real pool names.
    assert state == "[2JwipedFAKE LOG LINEgnp"


async def test_overlong_pool_name_is_truncated_not_dropped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Home Assistant refuses a state over 255 characters outright.

    Left unbounded, an over-long name does not just look wrong — it takes the
    sensor out entirely and logs the raw string. Truncating keeps the sensor
    working and the log clean.
    """
    mock_endpoints(
        aioclient_mock,
        overrides={
            API_MINING_POOLS: {
                "json": {"pools": [{"name": "A" * 5000, "blockCount": 5}]}
            }
        },
    )
    await _setup(hass, mock_config_entry)

    state = _state(hass, mock_config_entry, "top_pool").state
    assert state == "A" * MAX_STRING_LENGTH


async def test_ordinary_pool_names_are_unchanged(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The benign path: a real pool name survives sanitising intact.

    Real names contain spaces, punctuation and non-ASCII letters.
    """
    for name in ("Foundry USA", "F2Pool", "SlushPool (Braiins)", "Luxor — mining"):
        aioclient_mock.clear_requests()
        mock_endpoints(
            aioclient_mock,
            overrides={
                API_MINING_POOLS: {
                    "json": {"pools": [{"name": name, "blockCount": 5}]}
                }
            },
        )
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{BASE_URL}/{name}",
            data={"base_url": BASE_URL, "fast_interval": 60},
        )
        assert await _setup(hass, entry)
        assert _state(hass, entry, "top_pool").state == name


# --- unbounded collections ----------------------------------------------------


async def test_price_attributes_are_bounded(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The instance decides how many currencies it publishes.

    Every attribute is written to the state machine and the recorder on each
    poll, so an unbounded count is durable damage rather than a slow poll.
    Three thousand codes produced a ~39 KB state before this was capped.
    """
    codes = [
        "".join(c)
        for c in itertools.islice(
            itertools.product(string.ascii_uppercase, repeat=3), 3000
        )
    ]
    prices = {"time": 1, "USD": 95000} | {code: 1000 for code in codes}
    mock_endpoints(aioclient_mock, overrides={API_PRICES: {"json": prices}})

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_PRICE_ATTRIBUTES: True}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    attributes = _state(hass, mock_config_entry, "price_usd").attributes
    currency_attributes = [k for k in attributes if len(k) == 3 and k.isupper()]
    assert len(currency_attributes) <= MAX_CURRENCIES


async def test_a_normal_currency_list_is_untouched(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The benign path: a realistic set of fiats is exposed in full."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_PRICE_ATTRIBUTES: True}
    )
    mock_endpoints(aioclient_mock)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    attributes = _state(hass, mock_config_entry, "price_usd").attributes
    assert attributes["EUR"] == 88000
    assert attributes["AUD"] == 145000


async def test_array_endpoints_are_bounded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A huge array is truncated at ingest, not carried through the sensors."""
    block = {"height": 1, "timestamp": 1_700_000_000, "tx_count": 1}
    mock_endpoints(
        aioclient_mock,
        overrides={API_BLOCKS: {"json": [block] * (MAX_LIST_ITEMS + 5000)}},
    )

    assert len(await _client(hass).blocks()) == MAX_LIST_ITEMS


# --- out-of-range timestamps --------------------------------------------------


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        (
            "next_retarget",
            {
                API_DIFFICULTY: {
                    "json": {"progressPercent": 1, "estimatedRetargetDate": 1e30}
                }
            },
        ),
        (
            "latest_block_time",
            {API_BLOCKS: {"json": [{"height": 1, "timestamp": 1e30}]}},
        ),
    ],
)
async def test_out_of_range_timestamps_do_not_raise(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    field: str,
    payload: dict[str, Any],
) -> None:
    """An epoch the platform cannot represent yields no value, not an exception.

    These conversions run inside a state write, where an uncaught OverflowError
    takes down more than the one sensor that provoked it.
    """
    mock_endpoints(aioclient_mock, overrides=payload)
    assert await _setup(hass, mock_config_entry)

    assert _state(hass, mock_config_entry, field).state == "unknown"
    # The rest of the entry is unaffected.
    assert _state(hass, mock_config_entry, "block_height").state == "960953"


# --- shape confusion ----------------------------------------------------------


async def test_wrong_shape_does_not_reach_the_sensors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A reshaped payload fails the poll rather than erroring deep in a sensor."""
    mock_endpoints(
        aioclient_mock, overrides={API_MEMPOOL: {"json": ["not", "a", "dict"]}}
    )

    assert not await _setup(hass, mock_config_entry)


async def test_non_integer_chain_tip_is_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The endpoint is specified to return a bare integer.

    Anything else -- an object, a string, a list -- fails the poll rather than
    being coerced into something that only looks like a height.
    """
    for body in ('{"height": 5}', '"960953abc"', "[1]", "null"):
        aioclient_mock.clear_requests()
        mock_endpoints(aioclient_mock, overrides={API_TIP_HEIGHT: {"text": body}})

        with pytest.raises(MempoolApiError, match="not an integer"):
            await _client(hass).tip_height()


async def test_sensor_layer_rejects_an_implausible_height_independently() -> None:
    """The sensor guard holds even if a height reaches it unchecked.

    Defence in depth: the client bounds the height at ingest, but the cost of
    that single check being bypassed is a hung event loop rather than a wrong
    reading, so the arithmetic refuses to run on an absurd value too.
    """
    from custom_components.mempool.sensor import _blocks_to_halving, _subsidy

    for height in (MAX_BLOCK_HEIGHT + 1, 1e18, float("inf"), float("nan"), -5, "x"):
        assert _subsidy(height) is None, height
        assert _blocks_to_halving(height) is None, height

    # The benign path: a real height still computes.
    assert _subsidy(960953) == 3.125
    assert _blocks_to_halving(960953) == 89047


async def test_statistics_import_is_bounded(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A feed with more points than the ceiling imports only up to it.

    Each row is a durable statistics record written to the recorder database,
    and the instance chooses how many points to send.
    """
    from unittest.mock import patch

    from custom_components.mempool.const import API_HISTORICAL_PRICE

    # Distinct hours, so every point would otherwise become its own row.
    points = [{"time": 1_700_000_000 + i * 3600, "USD": 100 + i} for i in range(40)]
    mock_endpoints(
        aioclient_mock,
        overrides={API_HISTORICAL_PRICE: {"json": {"prices": points}}},
    )
    await _setup(hass, mock_config_entry)

    with (
        patch("custom_components.mempool.services.MAX_STATISTICS_ROWS", 10),
        patch(
            "homeassistant.components.recorder.statistics.async_import_statistics"
        ) as mock_import,
    ):
        await hass.services.async_call(
            DOMAIN,
            "import_price_history",
            {"config_entry_id": mock_config_entry.entry_id},
            blocking=True,
        )

    assert len(mock_import.call_args[0][2]) == 10
    assert "more than 10 hourly points" in caplog.text


async def test_unrepresentable_statistic_timestamps_are_skipped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """One bad epoch does not fail an import whose other rows are good."""
    from unittest.mock import patch

    from custom_components.mempool.const import API_HISTORICAL_PRICE

    points = [
        {"time": 10**18, "USD": 1},  # far beyond any representable date
        {"time": 1_700_000_000, "USD": 95000},
    ]
    mock_endpoints(
        aioclient_mock,
        overrides={API_HISTORICAL_PRICE: {"json": {"prices": points}}},
    )
    await _setup(hass, mock_config_entry)

    with patch(
        "homeassistant.components.recorder.statistics.async_import_statistics"
    ) as mock_import:
        await hass.services.async_call(
            DOMAIN,
            "import_price_history",
            {"config_entry_id": mock_config_entry.entry_id},
            blocking=True,
        )

    rows = mock_import.call_args[0][2]
    assert [row["mean"] for row in rows] == [95000]
