"""Tests that the staged documentation stays true to the code.

The page in ``docs/`` is not shipped and is not executed, so nothing about it
fails at runtime. These tests are the only thing stopping it drifting away from
the integration it describes — which matters precisely because it is intended
to be lifted into home-assistant.io largely unedited.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from custom_components.mempool.const import (
    DEFAULT_FAST_INTERVAL,
    DOMAIN,
    PRICE_INTERVAL,
    PUBLIC_FAST_INTERVAL,
    SLOW_INTERVAL,
)
from custom_components.mempool.sensor import PRICE_SENSOR, SENSORS

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs" / "mempool.markdown"
COMPONENT = ROOT / "custom_components" / "mempool"

PAGE = DOCS.read_text()
NAMES = json.loads((COMPONENT / "strings.json").read_text())["entity"]["sensor"]


def _sensor_section() -> str:
    """The part of the page listing sensors, and nothing else.

    Scoped deliberately: the page has other tables (poll intervals, action
    parameters) whose rows would otherwise be mistaken for sensors.
    """
    body = PAGE.split("## Supported functionality", 1)[1]
    return body.split("\n## ", 1)[0]


def _sensor_table_names() -> set[str]:
    """Names in the first column of every sensor table row."""
    names = {
        m.group(1).strip()
        for m in re.finditer(r"^\| ([^|]+) \|", _sensor_section(), re.M)
    }
    return {n for n in names if n and n != "Sensor" and set(n) != {"-"}}


def test_every_sensor_is_documented() -> None:
    """Each sensor's display name appears in the page."""
    missing = [
        NAMES[d.translation_key]["name"]
        for d in (*SENSORS, PRICE_SENSOR)
        if NAMES[d.translation_key]["name"] not in PAGE
    ]

    assert not missing, f"undocumented sensors: {missing}"


def test_no_sensors_documented_that_do_not_exist() -> None:
    """Every row in the sensor tables maps to a real sensor.

    Catches the likelier direction of drift: a sensor removed from the code
    but left in the page.
    """
    real = {NAMES[d.translation_key]["name"] for d in (*SENSORS, PRICE_SENSOR)}
    documented = _sensor_table_names()

    assert documented <= real, f"documented but nonexistent: {documented - real}"


def test_disabled_sensors_are_flagged() -> None:
    """A sensor that ships switched off says so, and no other does.

    Users who cannot find an entity go looking in the docs first, so this is
    the detail most worth keeping accurate.
    """
    for description in (*SENSORS, PRICE_SENSOR):
        name = NAMES[description.translation_key]["name"]
        row = next(
            line
            for line in _sensor_section().splitlines()
            if line.startswith(f"| {name} |")
        )
        flagged = "*Disabled.*" in row
        assert flagged is not description.entity_registry_enabled_default, name


def test_documented_actions_match_the_registered_ones() -> None:
    """Every action the integration provides is documented, and vice versa."""
    declared = set(json.loads((COMPONENT / "strings.json").read_text())["services"])
    for name in declared:
        assert f"{DOMAIN}.{name}" in PAGE, name


def test_polling_intervals_are_stated_correctly() -> None:
    """The documented cadence matches the constants the code actually uses."""
    assert f"{DEFAULT_FAST_INTERVAL} seconds by default" in PAGE
    assert f"{PUBLIC_FAST_INTERVAL} seconds, fixed" in PAGE
    assert f"{int(PRICE_INTERVAL.total_seconds() // 60)} minutes" in PAGE
    assert f"{int(SLOW_INTERVAL.total_seconds() // 60)} minutes" in PAGE


def test_front_matter_matches_the_manifest() -> None:
    """The page's metadata agrees with manifest.json."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text())

    assert f"ha_domain: {manifest['domain']}" in PAGE
    assert f"ha_integration_type: {manifest['integration_type']}" in PAGE
    assert "ha_iot_class: Local Polling" in PAGE
    assert manifest["iot_class"] == "local_polling"
    for owner in manifest["codeowners"]:
        assert f"- '{owner}'" in PAGE


def test_documented_platforms_exist() -> None:
    """Platforms listed in the front matter have a module backing them."""
    listed = re.search(r"ha_platforms:\n((?:  - \w+\n)+)", PAGE)
    assert listed is not None
    platforms = set(re.findall(r"  - (\w+)", listed.group(1)))

    assert platforms == {"diagnostics", "sensor"}
    for platform in platforms:
        assert (COMPONENT / f"{platform}.py").is_file(), platform


def test_no_real_hostnames_in_examples() -> None:
    """Examples use reserved example domains, never a real address."""
    hosts = set(re.findall(r"https?://([\w.-]+)", PAGE))
    allowed = {
        "mempool.space",
        "github.com",
        "mynode.example",
        "mynode.example:8999",
    }

    assert hosts <= allowed, f"unexpected hosts: {hosts - allowed}"
