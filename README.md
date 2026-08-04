# Mempool for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/derekclapham/ha-mempool/actions/workflows/validate.yaml/badge.svg)](https://github.com/derekclapham/ha-mempool/actions/workflows/validate.yaml)

A Home Assistant integration for a **self-hosted [mempool](https://github.com/mempool/mempool) instance** (Bitcoin Core + mempool +, typically, an Electrum server such as Fulcrum). Point it at your own node and get native Bitcoin sensors — price, on-chain status, fees and mempool state — with **no third-party API calls**. It also works against the public `https://mempool.space`.

Unlike the existing options (Home Assistant's core `bitcoin`/`blockchain` integrations and CoinGecko-based cards), this talks **directly to your node** over its local API, and can **backfill years of price history** into Home Assistant's long-term statistics in one call.

## Features

- 🔒 **Self-hosted first** — all data comes from your instance's REST API over your LAN.
- 🖥️ **UI config flow** — just enter your instance URL. No YAML.
- 💰 **Price in your currency** — the setup offers only the fiats your instance actually serves.
- 📈 **Instant price history** — the `mempool.import_price_history` service backfills long-term statistics from the node's `historical-price` feed.
- ⚙️ **Tunable polling** — three internal coordinators (fast / price / slow); the fast interval is adjustable so you can be gentle with public instances.

## Requirements

- Home Assistant **2025.1** or newer.
- A reachable [mempool](https://github.com/mempool/mempool) instance (your own, or `https://mempool.space`). The base URL must be reachable **from the Home Assistant host** — mind VLANs/firewalls if your node lives on a different subnet.
- The **BTC price** sensor requires the instance's optional **price feed** to be enabled. On-chain, fee and mempool sensors work regardless; if the price feed is off the integration simply sets up without the price sensor.

### Reverse proxies & HTTPS

A reverse proxy (nginx, Traefik, Caddy, Cloudflare Tunnel, …) in front of your instance needs no special support — just enter the **proxy's** URL as the base URL. For an HTTPS endpoint with a **self-signed** certificate, turn off **Verify SSL certificate** during setup. HTTP basic auth is not yet supported (planned).

## Sensors

Each config entry creates one device with the sensors below. All numeric sensors carry `state_class: measurement`, so Home Assistant records long-term statistics for charting.

| Sensor | Example | Notes |
| --- | --- | --- |
| BTC price | `A$90,962` | In the currency you pick — only if the price feed is enabled |
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
| Latest block miner | `Foundry USA` | Pool that mined the tip |
| Latest block reward / fees | `3.16 BTC` / `0.03 BTC` | Reward = subsidy + fees |
| Projected blocks | `8` | How many blocks the current mempool would fill |
| Next block fee | `1 sat/vB` | Median fee of the next projected block |
| Blocks to halving | `89,032` | Countdown to the next subsidy halving |
| Block subsidy | `3.125 BTC` | Current per-block subsidy |
| Blocks per hour | `7` | Blocks mined in the last rolling 60 min (target is 6) |
| Network pace | `117 %` | Block rate vs the 10-min target — 100% = on schedule |
| Top mining pool / share | `Foundry USA` / `26.5 %` | Over the last week |

Entities are named `sensor.mempool_<host>_<sensor>`, e.g. `sensor.mempool_mynode_local_8999_block_height`.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/derekclapham/ha-mempool`, category **Integration**.
2. Install **Mempool (self-hosted Bitcoin node)** and restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Mempool**.

### Manual

Copy `custom_components/mempool` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

Enter your instance's **base URL**, e.g. `http://mynode.local:8999` or `https://mempool.space`. The integration verifies it by calling `/api/v1/difficulty-adjustment` (which proves it's really a mempool API, not just a reverse proxy that answers). If a price feed is present, it then asks which currency to report — the dropdown lists only the fiats your instance actually publishes.

Polling cadence:

| Group | Data | Interval |
| --- | --- | --- |
| Fast | Chain tip, fees, mempool | **Configurable** (default 60 s, 15–3600 s) |
| Price | Spot price | 5 minutes |
| Slow | Difficulty adjustment, hashrate | 10 minutes |

The fast interval, SSL verification and price currency can all be changed later via the integration's **Configure** (options) — set the interval high for public instances.

### Changing the currency

The price sensor's identity includes its currency, so switching currency deliberately starts a **fresh price-history series**: a new price sensor is created for the new currency, and the previous one keeps its recorded history but stops updating (it'll show as unavailable — you can delete it if you don't want it). After switching, re-run **Import price history** to backfill the new currency. This avoids the alternative — reusing one sensor and changing its unit — which corrupts long-term statistics.

## Backfilling price history

Once set up, call the service to fill in historical price statistics:

```yaml
action: mempool.import_price_history
data:
  config_entry_id: <your mempool entry>
```

This pulls the node's `historical-price` feed for your currency, hour-aligns it, drops any placeholder points, and imports it as long-term statistics for the price sensor — so a history card is rich immediately instead of filling in over time. Safe to run more than once (it upserts per hour).

> **Note:** freshly imported statistics can take a minute or two to appear in *daily*-aggregated views; *hourly* views show them right away.

## Dashboard example

With the [apexcharts-card](https://github.com/RomRider/apexcharts-card) HACS card, a full price-history chart reads straight from the backfilled statistics:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: BTC / AUD — full history
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

- **"Failed to connect" during setup** — the URL must be reachable from the Home Assistant host. Test it: `curl http://<host>:<port>/api/v1/difficulty-adjustment`. Check VLAN/firewall rules if the node is on another subnet.
- **No price sensor** — the instance's price feed is disabled, or didn't return your currency. On-chain sensors are unaffected.
- **History card empty after backfill** — give the recorder a minute for daily aggregation, or use an hourly `period` in the card.

## Endpoints used

`/api/blocks/tip/height`, `/api/v1/difficulty-adjustment`, `/api/v1/fees/recommended`, `/api/mempool`, `/api/v1/mining/hashrate/3d`, `/api/v1/prices`, `/api/v1/historical-price`.

## Roadmap

Not in v0.1.0, planned for later:

- HTTP basic auth for protected instances.
- A logo in the Home Assistant UI (requires a separate PR to [home-assistant/brands](https://github.com/home-assistant/brands)).
- Automated tests and a diagnostics download.

## Disclaimer

Not affiliated with the mempool.space project. Bitcoin data is provided by your configured instance.

## License

MIT — see [LICENSE](LICENSE).
