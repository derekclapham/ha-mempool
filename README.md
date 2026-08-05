# Bitcoin Mempool for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/derekclapham/ha-mempool/actions/workflows/validate.yaml/badge.svg)](https://github.com/derekclapham/ha-mempool/actions/workflows/validate.yaml)

A Home Assistant integration for [mempool](https://github.com/mempool/mempool) — the Bitcoin blockchain and mempool explorer. Point it at the **public mempool.space** or **your own self-hosted instance** and get native Bitcoin sensors: price, latest block, on-chain status, fees, mempool state, mining, network pace and more (36 sensors).

Unlike Home Assistant's core `bitcoin`/`blockchain` integrations (which rely on third-party services), this talks to a real mempool instance — including your own node for a fully local setup — and can **backfill years of price history** into long-term statistics in one call.

## Features

- 🟠 **Public or self-hosted** — choose **mempool.space** in one step, or enter your own instance's URL.
- 🖥️ **UI config flow** — no YAML.
- 🧱 **Rich Bitcoin data** — price, latest block (miner, size, weight, reward, fees, median fee), difficulty and adjustment, fee tiers, mempool projection, halving countdown (blocks + estimated date), top mining pool, network pace, and 24-hour mining reward stats.
- 💰 **Price in your currency** — pick from the fiats your instance serves; optionally expose the rest as attributes for templating.
- 📈 **Instant price history** — the `mempool.import_price_history` service backfills long-term statistics from the `historical-price` feed.
- ⚙️ **Respectful polling** — three internal coordinators by cadence; self-hosted users tune the fast interval, while the public instance is locked to a gentle 5-minute poll.

## Requirements

- Home Assistant **2025.3** or newer (the sensor platform uses `AddConfigEntryEntitiesCallback`, which does not exist before 2025.3).
- Either the public **mempool.space**, or a reachable [mempool](https://github.com/mempool/mempool) instance of your own. A self-hosted URL must be reachable **from the Home Assistant host** (mind VLANs/firewalls if it's on another subnet).
- The **BTC price** sensor needs the instance's optional **price feed** enabled (mempool.space has it). On-chain, fee, mempool and mining sensors work regardless; without a price feed the integration simply sets up without the price sensor.

### Reverse proxies & HTTPS (self-hosted)

A reverse proxy (nginx, Traefik, Caddy, Cloudflare Tunnel, …) in front of your instance needs no special support — just enter the **proxy's** URL. For an HTTPS endpoint with a **self-signed** certificate, turn off **Verify SSL certificate** during setup. HTTP basic auth is not yet supported (planned).

## Sensors

Each config entry creates one device with the sensors below. All numeric sensors carry `state_class: measurement`, so Home Assistant records long-term statistics for charting.

| Sensor | Example | Notes |
| --- | --- | --- |
| BTC price | `$63,782` | In the currency you pick — only if the price feed is enabled |
| Block height | `960,956` | Current chain tip |
| Network hashrate | `937 EH/s` | From the 3-day mining average |
| Network difficulty | `126.23 T` | Trillions |
| Difficulty adjustment progress | `66.5 %` | Progress through the current 2016-block epoch |
| Estimated difficulty change | `+1.69 %` | Projected change at the next retarget |
| Blocks to retarget | `676` | |
| Next difficulty retarget | timestamp | Renders as a relative countdown |
| Fee — fastest / 30 min / 1 hour / economy / minimum | `1 sat/vB` | Five separate sensors |
| Mempool transactions | `74,363` | |
| Mempool size | `32.6 MvB` | Virtual size in millions of vB |
| Mempool total fees | `0.056 BTC` | Sum of fees of all mempool txs |
| Latest block | timestamp | Renders as "x min ago" |
| Latest block transactions / size / median fee | `2,955` / `1.29 MB` / `1 sat/vB` | |
| Latest block weight | `3.99 MWU` | Consensus limit is 4 MWU (= 4M weight units) |
| Latest block miner | `Foundry USA` | Pool that mined the tip |
| Latest block reward / fees | `3.16 BTC` / `0.03 BTC` | Reward = subsidy + fees |
| Projected blocks | `8` | How many blocks the current mempool would fill |
| Next block fee | `1 sat/vB` | Median fee of the next projected block |
| Blocks to halving | `89,032` | Countdown to the next subsidy halving |
| Next halving | timestamp | Estimated date of the next halving — renders as a countdown, and templates can derive the exact time remaining |
| Block subsidy | `3.125 BTC` | Current per-block subsidy |
| Blocks per hour | `7` | Blocks mined in the last rolling 60 min (target is 6) |
| Network pace | `117 %` | Block rate vs the 10-min target — 100% = on schedule |
| Top mining pool / share | `Foundry USA` / `26.5 %` | Over the last week |
| Mining reward (24h) | `453 BTC` | Total miner reward (subsidy + fees) over the last ~144 blocks |
| Mining fees (24h) | `3.9 BTC` | Total fees over the last ~144 blocks |
| Mean transaction fee (24h) | `615 sat` | Average fee per transaction over ~144 blocks |

Entities are named `sensor.mempool_<host>_<sensor>`, e.g. `sensor.mempool_mynode_local_8999_block_height`.

## Installation

### HACS (recommended)

Once it's in the HACS default store you'll be able to search **Bitcoin Mempool** directly. Until then, add it as a custom repository:

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/derekclapham/ha-mempool`, category **Integration**.
2. Install **Bitcoin Mempool** and restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Bitcoin Mempool**.

### Manual

Copy `custom_components/mempool` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

At setup, choose your instance:

- **mempool.space (public)** — no URL needed. Uses `https://mempool.space` and a fixed, gentle **5-minute** poll to respect the shared public API. The interval and SSL settings are locked.
- **Self-hosted instance** — enter your **base URL** (e.g. `http://mynode.local:8999`), optionally turn off **Verify SSL certificate** for a self-signed cert, and set the **fast poll interval**.

Either way, the URL is verified (via `/api/v1/difficulty-adjustment`, proving it's really a mempool API), then — if a price feed is present — you pick which currency to report (only the fiats the instance actually serves).

Polling cadence:

| Group | Data | Interval |
| --- | --- | --- |
| Fast | Chain tip, latest block, fees, mempool, projection | Self-hosted: **configurable** (default 60 s, 15–3600 s). Public: **300 s (locked)** |
| Price | Spot price | 5 minutes |
| Slow | Difficulty adjustment, hashrate, mining pool, reward stats | 10 minutes |

For a self-hosted instance, the fast interval, SSL verification and currency can be changed later under **Configure**. For the public instance, only the currency (and the attributes toggle below) are editable.

### Other currencies as attributes (opt-in)

At setup (and under **Configure**) you can tick **Expose other currencies as attributes**. When on, every other fiat your instance serves is attached to the price sensor as an attribute, so a template can read any of them:

```jinja
{{ state_attr('sensor.mempool_<host>_btc_price', 'EUR') }}
```

These attributes are **not** recorded as long-term statistics (only the sensor's chosen-currency state is) — they're purely for templating. Left off by default to keep the recorder lean.

### Changing the currency

The price sensor's identity includes its currency, so switching currency deliberately starts a **fresh price-history series**: a new price sensor is created for the new currency, and the previous one keeps its recorded history but stops updating (it'll show as unavailable — you can delete it if you don't want it). After switching, re-run **Import price history** to backfill the new currency. This avoids the alternative — reusing one sensor and changing its unit — which corrupts long-term statistics.

## Backfilling price history

Once set up, call the service to fill in historical price statistics:

```yaml
action: mempool.import_price_history
data:
  config_entry_id: <your Bitcoin Mempool entry>
```

This pulls the `historical-price` feed for your current currency, hour-aligns it, drops any placeholder points, and imports it as long-term statistics for the price sensor — so a history card is rich immediately instead of filling in over time. Safe to run more than once (it upserts per hour).

> **Note:** freshly imported statistics can take a minute or two to appear in *daily*-aggregated views; *hourly* views show them right away.

## Dashboard example

With the [apexcharts-card](https://github.com/RomRider/apexcharts-card) HACS card, a full price-history chart reads straight from the backfilled statistics:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: BTC / USD — full history
graph_span: 6y
span:
  end: day
series:
  - entity: sensor.mempool_mynode_local_8999_btc_price
    type: area
    statistics:
      type: mean
      period: day
```

## Troubleshooting

- **"Failed to connect" during setup (self-hosted)** — the URL must be reachable from the Home Assistant host. Test it: `curl http://<host>:<port>/api/v1/difficulty-adjustment`. Check VLAN/firewall rules if the node is on another subnet.
- **No price sensor** — the instance's price feed is disabled, or didn't return your currency. On-chain sensors are unaffected.
- **Can't find "Expose other currencies" under Configure** — it appears below the currency dropdown; hard-refresh your browser (Home Assistant caches integration translations), and note it only shows when the price feed is reachable.
- **History card empty after backfill** — give the recorder a minute for daily aggregation, or use an hourly `period` in the card.

## Endpoints used

`/api/blocks/tip/height`, `/api/v1/difficulty-adjustment`, `/api/v1/fees/recommended`, `/api/v1/fees/mempool-blocks`, `/api/mempool`, `/api/v1/blocks`, `/api/v1/mining/hashrate/3d`, `/api/v1/mining/pools/1w`, `/api/v1/mining/reward-stats/144`, `/api/v1/prices`, `/api/v1/historical-price`.

## Roadmap

- Listing in the **HACS default store**, so it installs without adding a custom repository (in progress).
- HTTP basic auth for protected instances.
- Automated tests and a diagnostics download.

## Disclaimer

Not affiliated with the mempool.space project. Bitcoin data is provided by your configured instance.

## License

MIT — see [LICENSE](LICENSE).
