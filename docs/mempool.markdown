---
title: Bitcoin Mempool
description: Instructions on how to integrate Bitcoin blockchain and mempool data from a mempool instance into Home Assistant.
ha_category:
  - Finance
  - Sensor
ha_release: TBD
ha_iot_class: Local Polling
ha_config_flow: true
ha_codeowners:
  - '@derekclapham'
ha_domain: mempool
ha_platforms:
  - diagnostics
  - sensor
ha_integration_type: service
ha_quality_scale: gold
---

The **Bitcoin Mempool** {% term integration %} brings Bitcoin blockchain and
mempool data into Home Assistant from a [mempool](https://github.com/mempool/mempool)
instance — the open-source Bitcoin blockchain and mempool explorer that powers
[mempool.space](https://mempool.space).

You can point it at the public mempool.space, or at your own self-hosted
instance. A self-hosted instance keeps everything on your own network: the
integration talks only to the address you give it, and never to a third-party
service.

It provides the current Bitcoin price, the state of the mempool and its fee
market, details of the most recent block, difficulty and hashrate, mining pool
distribution, and a countdown to the next halving.

## Use cases

- **Time an on-chain transaction.** The fee sensors show what the network is
  charging right now, so an automation can notify you when the fee to get into
  the next block drops below a threshold you are willing to pay.
- **Watch your own node.** If you run a mempool instance alongside a Bitcoin
  node, the block and mempool sensors show what your node is seeing rather than
  what a third-party service reports.
- **Track the price without a cloud service.** A self-hosted instance with its
  price feed enabled gives a Bitcoin price sensor with no external dependency,
  and years of history can be backfilled in a single action call.
- **Follow network health.** Hashrate, difficulty, block production rate and
  mining pool concentration are recorded as long-term statistics, so they chart
  over months without any extra configuration.

## Supported instances

The integration works with any instance that serves the mempool REST API:

- **mempool.space** — the public instance. Selected in one step during setup,
  with no URL to enter.
- **A self-hosted mempool instance** — any deployment exposing the same REST
  API, including one behind a reverse proxy. Both HTTP and HTTPS are supported,
  and certificate verification can be turned off for a self-signed certificate.

These are not supported:

- **Bitcoin Core's RPC interface** and other block explorers, such as a bare
  Esplora deployment. The integration checks the URL really is a mempool API
  during setup and refuses anything else.
- **Instances requiring authentication.** There is no support for HTTP basic
  auth or any other credential; a protected instance cannot be used.
- **Non-Bitcoin mempool deployments**, such as the Liquid sidechain instances.
  The sensors assume Bitcoin mainnet semantics — the halving countdown and
  block subsidy in particular.

The optional **price feed** is a separate matter. It is enabled on
mempool.space but is off by default on many self-hosted deployments, and the
Bitcoin price sensor only exists when the instance actually serves it. Every
other sensor works either way.

{% include integrations/config_flow.md %}

{% configuration_basic %}
Instance:
  description: Choose between the public mempool.space and a self-hosted instance. Selecting mempool.space needs no further connection details.
Base URL:
  description: "Self-hosted only. The address of your mempool web server, including the scheme, host and port — for example `http://mynode.example:8999`. If it sits behind a reverse proxy, enter the proxy's address. The address must be reachable from the Home Assistant host, which matters if your node is on a different VLAN or subnet."
Verify SSL certificate:
  description: Self-hosted only. Turn this off for an HTTPS instance using a self-signed certificate. Leave it on otherwise.
Fast poll interval:
  description: Self-hosted only. How often to poll fast-changing data, in seconds. Defaults to 60, and accepts 15 to 3600. The public instance is fixed at 300 seconds and does not offer this.
Currency:
  description: Only shown when the instance serves a price feed. Lists the fiat currencies your instance actually publishes, and sets the unit of the Bitcoin price sensor.
Expose other currencies as attributes:
  description: Optional. Attaches every other fiat your instance serves to the price sensor as attributes, for use in templates. These attributes are not recorded as long-term statistics. Off by default.
{% endconfiguration_basic %}

The URL is verified before the entry is created. The integration requests
`/api/v1/difficulty-adjustment` and checks the response looks like a mempool
API, so a web server that merely answers on that address is rejected rather
than being set up and then failing.

Each configured instance becomes one device, and the same instance cannot be
added twice.

## Configuration options

These can be changed after setup from the integration's **Configure** dialog.

{% configuration_basic %}
Fast poll interval:
  description: Self-hosted only. How often to poll chain tip, fees and mempool data, in seconds.
Verify SSL certificate:
  description: Self-hosted only. Whether to validate the instance's TLS certificate.
Currency:
  description: Which fiat the Bitcoin price sensor reports. Only shown when the instance serves a price feed, and re-checked each time the dialog opens, so a feed enabled after setup appears here.
Expose other currencies as attributes:
  description: Whether to attach the remaining fiats to the price sensor as attributes.
{% endconfiguration_basic %}

Changing the currency deliberately starts a **new price history series**. The
price sensor's identity includes its currency, so a new sensor is created and
the previous one keeps its recorded history but stops updating. This avoids
reusing one sensor and silently changing its unit, which would corrupt its
long-term statistics. After switching, run the **Import price history** action
again to backfill the new currency.

If your instance moves to a different address, use **Reconfigure** rather than
deleting and re-adding the entry. Reconfiguring keeps every sensor and all of
its recorded history.

## Supported functionality

Each configured instance creates one device with the sensors below.

Sensors marked *Disabled* are created but switched off, because they restate a
value another sensor already shows, use an obscure unit, or break down a figure
that is more useful in summary. Enable any of them from the entity's settings.

### Bitcoin price

| Sensor | Unit | Notes |
| --- | --- | --- |
| BTC price | Your chosen fiat | Only created when the instance serves a price feed |

### Mempool and fees

| Sensor | Unit | Notes |
| --- | --- | --- |
| Fee (fastest) | sat/vB | Fee to be included in the next block |
| Fee (30 min) | sat/vB | |
| Fee (1 hour) | sat/vB | |
| Fee (economy) | sat/vB | |
| Fee (minimum) | sat/vB | The instance's relay minimum |
| Mempool transactions | tx | Transactions waiting to be confirmed |
| Mempool size | MvB | Virtual size, in millions of virtual bytes |
| Mempool total fees | BTC | Total fees offered by everything in the mempool |
| Next block fee | sat/vB | Median fee of the next projected block |
| Projected blocks | blocks | *Disabled.* How many blocks the current mempool would fill |

### Latest block

| Sensor | Unit | Notes |
| --- | --- | --- |
| Latest block | Timestamp | Renders as "x minutes ago" |
| Latest block transactions | tx | |
| Latest block size | MB | |
| Latest block miner | | The mining pool that found the block |
| Latest block reward | BTC | Subsidy plus fees |
| Latest block fees | BTC | |
| Latest block median fee | sat/vB | *Disabled.* What was actually paid, rather than what is recommended |
| Latest block weight | MWU | *Disabled.* Millions of weight units; the consensus limit is 4 MWU |

### Chain and network

| Sensor | Unit | Notes |
| --- | --- | --- |
| Block height | | Current chain tip |
| Network hashrate | EH/s | From the three-day mining average |
| Network difficulty | T | Trillions |
| Difficulty adjustment progress | % | Progress through the current 2016-block epoch |
| Estimated difficulty change | % | Projected change at the next retarget |
| Blocks to retarget | blocks | |
| Next difficulty retarget | Timestamp | |
| Blocks per hour | blocks/h | Blocks found in the last rolling 60 minutes; the target is 6 |
| Network pace | % | *Disabled.* Block rate against the 10-minute target, where 100% is on schedule |

### Halving

| Sensor | Unit | Notes |
| --- | --- | --- |
| Blocks to halving | blocks | |
| Block subsidy | BTC | The current per-block subsidy |
| Next halving | Timestamp | Estimated, anchored to the latest block rather than recalculated every poll |

### Mining

| Sensor | Unit | Notes |
| --- | --- | --- |
| Top mining pool | | Largest pool over the last week |
| Mining reward (24h) | BTC | Total miner reward over roughly the last 144 blocks |
| Top pool share | % | *Disabled.* The top pool's share of blocks over the last week |
| Mining fees (24h) | BTC | *Disabled.* Fees only, excluding the subsidy |
| Mean transaction fee (24h) | sat | *Disabled.* Average fee per transaction |

Every numeric sensor carries a `measurement` state class, so Home Assistant
records long-term statistics and they chart over any period without further
configuration.

## Data updates

The integration {% term polling polls %} its instance. Nothing is pushed, since
the mempool REST API offers no subscription mechanism the integration uses.

Data is split into three groups, each polled at a rate matching how quickly it
actually changes, so that a self-hosted node is queried usefully without the
public API being queried wastefully:

| Group | Data | Interval |
| --- | --- | --- |
| Fast | Chain tip, latest block, fees, mempool, projection | Self-hosted: 60 seconds by default, configurable from 15 to 3600. Public: 300 seconds, fixed |
| Price | Bitcoin spot price | 5 minutes |
| Slow | Difficulty, hashrate, mining pools, reward statistics | 10 minutes |

The **fast** interval is the only one you can change, and only for a
self-hosted instance. On mempool.space it is fixed at 300 seconds to be a
considerate user of a free, shared public service — a Bitcoin block arrives
roughly every 10 minutes, so polling faster gains very little.

The **price** and **slow** intervals are fixed for everyone. A five-minute
price is ample for charting, and difficulty retargets happen about every two
weeks.

Each group succeeds or fails independently. If one poll fails, only that
group's sensors become unavailable, and the failure is logged once rather than
on every retry. The sensors return when the next poll succeeds.

If a sensor's specific value is missing from an otherwise successful poll, it
reports `unknown` rather than `unavailable`, which is reserved for not being
able to reach the instance at all.

You can force an immediate refresh with the
[`homeassistant.update_entity`](/integrations/homeassistant/#action-update-entity)
action.

## Actions

{% include integrations/actions.md %}

### Action: Import price history

Backfills Home Assistant's long-term statistics for the Bitcoin price sensor
from the instance's historical price feed. Without it, a price chart starts
empty and fills in from the moment you set the integration up; with it, years
of history appear at once.

| Data attribute | Optional | Description |
| --- | --- | --- |
| `config_entry_id` | No | The mempool instance to import history for. |

The feed is fetched for the currency currently configured, aligned to hourly
statistics, and imported for the price sensor. Placeholder points that some
instances emit before a currency pair existed are discarded.

Running it more than once is safe: each hour is updated in place rather than
duplicated.

```yaml
action: mempool.import_price_history
data:
  config_entry_id: 01JBEXAMPLEENTRYID
```

{% note %}
Freshly imported statistics can take a minute or two to appear in views
aggregated by day. Hourly views show them straight away.
{% endnote %}

## Examples

### Notify when on-chain fees are cheap

```yaml
{% raw %}automation:
  - alias: "Notify when Bitcoin fees are low"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.mempool_mynode_example_8999_fee_fastest
        below: 5
        for: "00:10:00"
    actions:
      - action: notify.notify
        data:
          message: >-
            Next-block fee is {{ states('sensor.mempool_mynode_example_8999_fee_fastest') }}
            sat/vB — a good time to move coins.{% endraw %}
```

### Announce a new block

```yaml
{% raw %}automation:
  - alias: "Announce each new Bitcoin block"
    triggers:
      - trigger: state
        entity_id: sensor.mempool_mynode_example_8999_block_height
    conditions:
      - condition: template
        value_template: "{{ trigger.from_state.state not in ['unknown', 'unavailable'] }}"
    actions:
      - action: persistent_notification.create
        data:
          title: "Block {{ trigger.to_state.state }}"
          message: >-
            Mined by {{ states('sensor.mempool_mynode_example_8999_latest_block_miner') }},
            reward {{ states('sensor.mempool_mynode_example_8999_latest_block_reward') }} BTC.{% endraw %}
```

### Time remaining until the halving

The halving sensor is a timestamp, so a template can turn it into whatever form
you want to display:

```jinja
{% raw %}{% set halving = states('sensor.mempool_mynode_example_8999_next_halving') | as_datetime %}
{{ (halving - now()).days }} days to go{% endraw %}
```

### Read a currency you did not select

With **Expose other currencies as attributes** enabled:

```jinja
{% raw %}{{ state_attr('sensor.mempool_mynode_example_8999_btc_price', 'EUR') }}{% endraw %}
```

### Chart the full price history

After running the **Import price history** action, a statistics-based chart
shows the whole series:

```yaml
type: statistic
entity: sensor.mempool_mynode_example_8999_btc_price
period:
  calendar:
    period: month
stat_type: mean
```

## Known limitations

- **Instances requiring authentication are not supported.** There is no way to
  supply HTTP basic auth credentials or any other secret, so a protected
  instance cannot be configured.
- **The Bitcoin price sensor depends on an optional feed.** Many self-hosted
  deployments ship with the price feed disabled, and the sensor is not created
  when it is unavailable. A repair issue explains this when it happens on a
  self-hosted instance, since it is something you can switch on.
- **Bitcoin mainnet only.** The halving countdown, block subsidy and difficulty
  sensors assume mainnet rules, so testnet, signet and sidechain deployments
  are not meaningful.
- **The public instance's poll interval cannot be changed.** It is fixed at 5
  minutes out of consideration for a shared free service.
- **Blocks per hour is measured over the recent blocks the API returns**, which
  comfortably covers an hour in practice but would undercount if the network
  ever produced more than about 15 blocks in one hour.
- **No transaction or address tracking.** The integration reports network-wide
  and block-level data; it cannot watch a particular address or transaction.
- **Historical price import covers the price sensor only.** There is no
  equivalent backfill for the on-chain or mining sensors.

## Troubleshooting

### Setup fails with "Failed to connect"

The address must be reachable from the Home Assistant host, which is not
necessarily the machine you are browsing from.

Check it from the Home Assistant host:

```bash
curl http://mynode.example:8999/api/v1/difficulty-adjustment
```

A JSON response containing `progressPercent` means the address is right. If the
request fails, the usual causes are a firewall or VLAN rule between Home
Assistant and the node, or an address that points at the node's Bitcoin RPC
port rather than the mempool web server.

The same error appears if the address answers but is not a mempool API — for
example a reverse proxy default page, or a different block explorer.

### The Bitcoin price sensor is missing

The instance is not serving a price feed, or is not serving the currency you
chose. On a self-hosted instance the price feed is an optional component that
is frequently left switched off; enabling it in your instance's configuration
and reloading the entry creates the sensor.

A repair issue is raised for this on self-hosted instances. No issue is raised
for mempool.space, because an outage there is not something you can fix.

All other sensors are unaffected.

### The currency picker does not list the currency I want

Only currencies your instance actually publishes are offered. The list is
re-checked each time you open the options dialog, so a currency added on the
instance appears after reopening it.

### A price chart is empty after importing history

Statistics aggregated by day take a minute or two to become visible. Choose an
hourly period to see them immediately.

### Some sensors show "unknown"

The instance answered but did not include that particular value. This is
normal for a brand-new instance that has not finished indexing, and for mining
pool sensors on an instance with no blocks in its window yet. Sensors showing
`unavailable` instead mean the instance could not be reached at all.

### Collecting diagnostics

The integration supports a diagnostics download from its entry menu. The
instance address is redacted, so the file is safe to attach to a bug report.

## Remove the integration

This integration follows standard integration removal. No extra steps are
required.

{% include integrations/remove_device_service.md %}

Removing the configuration entry deletes its device, all of its sensors, and
any repair issue it raised.

Long-term statistics recorded for those sensors are not deleted with them,
including anything backfilled by the **Import price history** action. Home
Assistant keeps them until they are purged. To remove them straight away, go to
**Developer tools** > **Statistics**, where they are listed as no longer having
an entity, and delete them there.
