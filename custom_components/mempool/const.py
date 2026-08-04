"""Constants for the Mempool (self-hosted Bitcoin node) integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.const import Platform

DOMAIN = "mempool"
LOGGER = logging.getLogger(__package__)
# Only a sensor platform for now; kept as a list so more can be added later.
PLATFORMS: list[Platform] = [Platform.SENSOR]

# Keys used in ConfigEntry.data / ConfigEntry.options. base_url + currency are
# captured during the config flow; fast_interval starts in data and, once the
# user edits it, is overridden from options (see __init__.async_setup_entry).
CONF_BASE_URL = "base_url"
CONF_CURRENCY = "currency"
CONF_FAST_INTERVAL = "fast_interval"
CONF_VERIFY_SSL = "verify_ssl"

DEFAULT_NAME = "Mempool"
DEFAULT_FAST_INTERVAL = 60  # seconds — chain tip/fees/mempool don't change faster
DEFAULT_VERIFY_SSL = True  # off lets an instance behind self-signed HTTPS work

# Fixed poll intervals for the two groups that don't warrant user tuning.
# Price moves slowly enough that 5 min is plenty; difficulty/hashrate barely
# move within a 10 min window (retargets are ~2 weeks apart).
PRICE_INTERVAL = timedelta(seconds=300)
SLOW_INTERVAL = timedelta(seconds=600)

# API paths, relative to the instance base URL. Grouped by the coordinator that
# fetches them (see coordinator.py). Shapes handled in api.py / sensor.py:
#   tip/height        -> bare integer (e.g. 960953), not JSON object
#   difficulty        -> {progressPercent, difficultyChange, remainingBlocks,
#                         estimatedRetargetDate (ms epoch), ...}
#   fees              -> {fastestFee, halfHourFee, hourFee, economyFee, minimumFee}
#   mempool           -> {count, vsize (vB), total_fee (sats), ...}
#   hashrate          -> {currentHashrate (H/s), currentDifficulty, ...}
#   prices            -> {time, USD, EUR, ... , AUD}  (fiats vary per instance)
#   historical-price  -> {prices: [{time, <CUR>, ...}, ...]}  (optional feed)
#   blocks            -> [{height, timestamp, tx_count, size, weight, extras:{
#                         reward, totalFees, medianFee, pool:{name}}}, ...]
#   mempool-blocks    -> [{nTx, medianFee, ...}, ...]  (projected next blocks)
#   mining/pools/1w   -> {pools: [{name, blockCount, rank}, ...]}
API_TIP_HEIGHT = "/api/blocks/tip/height"
API_DIFFICULTY = "/api/v1/difficulty-adjustment"
API_FEES = "/api/v1/fees/recommended"
API_MEMPOOL = "/api/mempool"
API_HASHRATE = "/api/v1/mining/hashrate/3d"
API_PRICES = "/api/v1/prices"
API_HISTORICAL_PRICE = "/api/v1/historical-price"
API_BLOCKS = "/api/v1/blocks"
API_MEMPOOL_BLOCKS = "/api/v1/fees/mempool-blocks"
API_MINING_POOLS = "/api/v1/mining/pools/1w"

# Bitcoin constants for computed sensors.
HALVING_INTERVAL = 210_000  # blocks between subsidy halvings
INITIAL_SUBSIDY = 50  # BTC block subsidy before the first halving

# Service to backfill price history into long-term statistics (see services.py).
SERVICE_IMPORT_PRICE_HISTORY = "import_price_history"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
