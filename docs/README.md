# Documentation staged for a Home Assistant core submission

`mempool.markdown` in this folder is the integration's documentation page,
written in the format the [home-assistant.io][hass-io] repository expects —
Jekyll front matter, `{% raw %}{% term %}{% endraw %}` shortcodes, `{% raw %}{% include %}{% endraw %}` partials and all.

## Why it lives here

The integration quality scale has thirteen `docs-*` rules across Bronze, Silver
and Gold. All of them are satisfied by a page on home-assistant.io, and that
repository only accepts pages for integrations that are in core — the
documentation pull request accompanies the core submission rather than
preceding it.

Writing the content is not blocked by any of that, only publishing it is. So
the page is written and kept current here. If this integration is ever
submitted to core, the file moves to
`source/_integrations/mempool.markdown` in the home-assistant.io repository
essentially unchanged.

Nothing in this folder ships to users. The HACS release archive is built from
`custom_components/mempool/` only.

## Before submitting

Two front matter fields are placeholders that cannot be filled in until the
core pull request exists:

- `ha_release` — the Home Assistant version the integration first appears in.
- `ha_quality_scale` — only meaningful once core assesses it. Set to the tier
  the code currently meets.

## Which rule each section satisfies

| Rule | Tier | Section |
| --- | --- | --- |
| `docs-high-level-description` | Bronze | Opening paragraphs |
| `docs-installation-instructions` | Bronze | *Configuration* (`config_flow.md` partial) |
| `docs-removal-instructions` | Bronze | *Remove the integration* |
| `docs-actions` | Bronze | *Actions* |
| `docs-triggers` | Bronze | n/a — provides no triggers |
| `docs-conditions` | Bronze | n/a — provides no conditions |
| `docs-installation-parameters` | Silver | *Configuration* → `configuration_basic` |
| `docs-configuration-parameters` | Silver | *Configuration options* → `configuration_basic` |
| `docs-supported-devices` | Gold | *Supported instances* |
| `docs-supported-functions` | Gold | *Supported functionality* |
| `docs-data-update` | Gold | *Data updates* |
| `docs-use-cases` | Gold | *Use cases* |
| `docs-examples` | Gold | *Examples* |
| `docs-known-limitations` | Gold | *Known limitations* |
| `docs-troubleshooting` | Gold | *Troubleshooting* |

## Keeping it honest

The page repeats things the code already knows — the sensor list, which sensors
ship disabled, the polling intervals, the front matter metadata. That is exactly
the sort of duplication that rots quietly, so `tests/test_docs.py` checks it
against the source on every run. Adding a sensor without documenting it, or
leaving a documented sensor behind after removing it, fails the suite.

It earned its place immediately: the first run caught the page calling the price
sensor *Bitcoin price* when the entity is actually named *BTC price*.

[hass-io]: https://github.com/home-assistant/home-assistant.io
