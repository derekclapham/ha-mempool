"""Tests that the translation files stay consistent with the code.

`strings.json` and `translations/en.json` must be byte-identical: editing one
and not the other leaves the affected entity with no name, and its entity_id
silently collapses to just the device name.
"""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.mempool.sensor import PRICE_SENSOR, SENSORS

COMPONENT = Path(__file__).parent.parent / "custom_components" / "mempool"
STRINGS = COMPONENT / "strings.json"
EN = COMPONENT / "translations" / "en.json"


def test_strings_and_en_are_byte_identical() -> None:
    """The English translation is a byte-for-byte copy of strings.json."""
    assert STRINGS.read_bytes() == EN.read_bytes()


def test_every_sensor_has_a_translated_name() -> None:
    """Each described sensor has a matching entity translation entry."""
    strings = json.loads(STRINGS.read_text())
    named = strings["entity"]["sensor"]

    for description in (*SENSORS, PRICE_SENSOR):
        assert description.translation_key is not None, description.key
        assert description.translation_key in named, description.key
        assert named[description.translation_key].get("name"), description.key


def test_no_orphan_entity_translations() -> None:
    """Every entity translation entry is actually used by a sensor."""
    strings = json.loads(STRINGS.read_text())
    used = {
        description.translation_key for description in (*SENSORS, PRICE_SENSOR)
    }

    assert set(strings["entity"]["sensor"]) == used


def test_config_flow_steps_are_described() -> None:
    """Every config-flow step and field has user-facing text."""
    config = json.loads(STRINGS.read_text())["config"]

    for step in ("user", "self_hosted", "currency"):
        assert step in config["step"], step

    # Each collected field has both a label and a description.
    for step in ("self_hosted", "currency"):
        fields = config["step"][step]["data"]
        descriptions = config["step"][step]["data_description"]
        assert set(fields) == set(descriptions), step
