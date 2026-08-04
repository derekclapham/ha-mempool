# Changelog

All notable changes to Machete are documented here.

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
