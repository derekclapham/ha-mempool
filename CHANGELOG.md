# Changelog

All notable changes to this integration are documented here.

## [0.5.0] - 2026-08-05

## [0.5.0] - 2026-08-05

The largest release so far. The integration now meets the Bronze, Silver and
Gold tiers of the Home Assistant Integration Quality Scale, gained a full test
suite where it previously had none, and has been through a security review.

Existing installations upgrade in place. No entity IDs, unique IDs or device
identifiers changed, and no recorded history is affected.

### Features

- **Diagnostics download.** Available from the integration's entry menu. The
  instance address is redacted, so the file is safe to attach to a bug report.
- **Reconfigure flow.** If your instance moves to a new address, change it from
  the entry menu instead of deleting and re-adding, which would have discarded
  every sensor's recorded history.
- **Repair issue for a missing price feed.** A self-hosted instance whose
  optional price feed is switched off now raises an actionable repair notice
  rather than a warning buried in the log. Not raised for mempool.space, where
  the price feed is not something you can fix.
- **Clearer setup errors.** A malformed address is rejected in the config flow
  with its own message, instead of surfacing later as a confusing connection
  failure. Stray whitespace around a pasted URL is trimmed.
- **Translatable error messages** for the `import_price_history` action.

### Behaviour changes

- **`unknown` and `unavailable` now mean different things.** A sensor reports
  `unavailable` only when the instance cannot be reached. When the instance
  answers but a particular value is absent from its response, the sensor now
  reports `unknown`. Affects the mining pool sensors on an empty pool list, the
  latest-block sensors on an empty block list, and the price sensor if its
  currency disappears. Neither state contributes to long-term statistics, so
  recorded history is unchanged.
- **Seven sensors now ship switched off** — Latest block weight, Latest block
  median fee, Projected blocks, Network pace, Top pool share, Mining fees (24h)
  and Mean transaction fee (24h). Each either restates a value another sensor
  already shows, uses an obscure unit, or breaks down a figure that is more
  useful in summary.

  **This applies to new installations only.** Entities already registered stay
  exactly as they are. To match the new defaults on an existing install,
  disable them from each entity's settings.
- **Latest block size** now carries the Data size device class, so Home
  Assistant can convert its unit for display.
- **The device model** now distinguishes a mempool.space entry from a
  self-hosted one. Previously every entry was labelled as self-hosted. Display
  only; device identity is unchanged.

### Security

The instance an entry points at is now treated as untrusted input throughout —
a compromised host, a hijacked DNS record, an intercepting proxy and a mistyped
address all deliver the same thing.

- Response bodies are read against a size ceiling and abandoned past it, rather
  than being buffered whole. Responses are decompressed without any ratio limit
  by the HTTP layer, so a small reply can otherwise expand enormously.
- Numbers must be finite. `NaN` and `Infinity` are refused, and so is an
  ordinary-looking literal that overflows to infinity — blocking only the
  obvious spelling is no defence.
- The chain tip height is range-checked. It is used as an exponent when
  deriving the block subsidy, where an implausible value is not a wrong reading
  but unbounded work inside Home Assistant's event loop.
- Mining pool names are sanitised and length-capped before becoming sensor
  states. Control and format characters carry terminal escape sequences,
  forged log lines and text-direction overrides.
- Collections are bounded where the data enters: array responses, the
  currencies exposed as price attributes, and the rows a single price-history
  import may create.
- Responses are checked to be the shape they are supposed to be, so a reshaped
  reply fails the update cleanly instead of raising somewhere unrelated.
- The base URL is validated as an `http`/`https` address before any request is
  attempted. Which host it names is deliberately unrestricted — pointing at a
  node on your own network is the normal case.
- **`SECURITY.md`** documents the principles, the scope, and how to report a
  vulnerability privately.

### Documentation

- Full integration documentation written in the format home-assistant.io
  expects, staged in `docs/`. This covers eleven of the quality scale's
  documentation rules; publishing them requires the integration to be in Home
  Assistant core, which writing them does not.
- README refreshed: notes the disabled-by-default sensors, uses reserved
  example hostnames, and drops roadmap items that have landed.

### Internal

- **Test suite added.** 167 tests at 100% statement coverage across all nine
  modules, where there were previously none. Includes regression tests that
  replay each confirmed security finding.
- **CI now runs the tests**, alongside Home Assistant's ruff conventions, mypy
  in strict mode, a 95% coverage floor, and a check that `strings.json` and
  `translations/en.json` stay identical.
- The `import_price_history` action is registered in `async_setup` rather than
  per config entry, so Home Assistant can validate automations that call it
  even when no entry is loaded.
- Entity icons moved into `icons.json`.
- Base entity extracted into `entity.py`.
- Release workflow hardened: the release tag is passed as an environment
  variable rather than interpolated into a shell command, non-semver tags are
  refused, git credentials are dropped after checkout, concurrent publishes of
  the same tag are serialised, and a `SHA256SUMS` file is published beside the
  release archive.

### Quality scale

Bronze, Silver and Gold are met in full, apart from the documentation rules,
which need a page on home-assistant.io and therefore a Home Assistant core
submission. Platinum is partially met: `strict-typing` is done, while
`async-dependency` and `inject-websession` both require the API client to be
published as a separate library.

### Requirements

Unchanged. Home Assistant **2025.3.0** or newer, and no third-party runtime
dependencies.

## [0.4.0] - 2026-08-05

### Fixes
- Declare the correct Home Assistant minimum version requirement.

### Documentation
- Refresh README to reflect current project state.

### Internal
- Validate brands via the inline brand/ folder in CI.

## [Unreleased]

### Fixes
- Declare the real Home Assistant minimum. The sensor platform imports `AddConfigEntryEntitiesCallback`, which only exists from 2025.3.0, but `hacs.json` and the README advertised 2025.1 — so HACS would offer the integration to installs where the sensor platform raises `ImportError` and the config entry fails to set up. Neither CI job catches this: hassfest runs against Home Assistant `master`, and the HACS action does not resolve imports against the declared minimum.

## [0.3.0] - 2026-08-04

### Features
- Add estimated next-halving timestamp sensor to track Bitcoin halving events
- Ship brand icons and logos with the integration for improved visual identification

### Improvements
- Automate manifest version syncing from release branch to reduce manual maintenance
- Enhance release process with automatic versioning via zip_release

### Internal
- Stop tracking local icon source files to reduce repository size

## [0.2.0] - 2026-08-04

### Features
- Add support for choosing between mempool.space or self-hosted mempool instance during setup
- Add 24-hour mining reward statistics with optional multi-currency attributes
- Add latest block weight sensor
- Add network-pace sensors tracking blocks per hour and percentage of schedule
- Add latest-block, mempool-projection, halving, and mining-pool sensors

### Fixes
- Fix import_price_history to respect the configured currency option

### Improvements
- Refresh README with updated documentation and branding

### Documentation
- Rename project to "Bitcoin Mempool" throughout documentation

## [0.1.0] - 2026-08-04

# Features

- Add mempool integration for a self-hosted Bitcoin node
- Default integer sensors to whole-number display precision

# Documentation

- Add README and changelog

# Internal

- Add HACS metadata, license, CI and gitignore

## [0.1.0] - 2026-08-04

# Release Notes

### Features
- Add mempool integration for a self-hosted Bitcoin node

### Documentation
- Add comprehensive README
