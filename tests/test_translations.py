"""Tests that the translation files stay consistent with the code.

`strings.json` and `translations/en.json` must be byte-identical: editing one
and not the other leaves the affected entity with no name, and its entity_id
silently collapses to just the device name.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import yaml

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


def test_service_actions_are_described() -> None:
    """Every action and every field it takes has user-facing text.

    services.yaml carries only the field schema, so the action's name, its
    description and each field's text have to come from strings.json.
    """
    strings = json.loads(STRINGS.read_text())
    services = strings["services"]
    declared = yaml.safe_load((COMPONENT / "services.yaml").read_text())

    assert set(services) == set(declared)

    for name, service in services.items():
        assert service["name"]
        assert service["description"]
        assert set(service.get("fields", {})) == set(
            declared[name].get("fields", {})
        )
        for field in service.get("fields", {}).values():
            assert field["name"]
            assert field["description"]


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


def test_every_sensor_has_an_icon() -> None:
    """Icons live in icons.json, keyed by translation key."""
    icons = json.loads((COMPONENT / "icons.json").read_text())["entity"]["sensor"]

    for description in (*SENSORS, PRICE_SENSOR):
        assert description.translation_key in icons, description.key
        assert icons[description.translation_key]["default"].startswith("mdi:")


def test_no_orphan_icons() -> None:
    """Every icons.json entry belongs to a sensor that exists."""
    icons = json.loads((COMPONENT / "icons.json").read_text())["entity"]["sensor"]
    used = {d.translation_key for d in (*SENSORS, PRICE_SENSOR)}

    assert set(icons) == used


def test_descriptions_do_not_carry_icons() -> None:
    """Icons must not be defined in both places.

    The icon-translations rule is explicit that the `icon` attribute comes off
    the EntityDescription once icons.json exists, so the two cannot drift.
    """
    for description in (*SENSORS, PRICE_SENSOR):
        assert description.icon is None, description.key


def test_exception_messages_are_translatable() -> None:
    """Every translation key raised by the code has a message.

    The exception-translations rule is satisfied by the raise sites carrying a
    key; this checks the other end, since a missing entry surfaces to the user
    as the raw key rather than a sentence.
    """
    strings = json.loads(STRINGS.read_text())
    messages = strings["exceptions"]

    source = (COMPONENT / "services.py").read_text()
    raised = set(re.findall(r'translation_key="([^"]+)"', source))
    assert raised, "no translation keys found in services.py"

    assert raised <= set(messages), f"missing: {raised - set(messages)}"
    assert set(messages) == raised, f"orphans: {set(messages) - raised}"

    for key, entry in messages.items():
        assert entry["message"].strip(), key


def test_exception_placeholders_are_supplied() -> None:
    """A message placeholder with no matching argument renders as a literal."""
    strings = json.loads(STRINGS.read_text())
    source = (COMPONENT / "services.py").read_text()

    for key, entry in strings["exceptions"].items():
        placeholders = set(re.findall(r"\{(\w+)\}", entry["message"]))
        if not placeholders:
            continue
        # The raise site for this key must pass every placeholder it uses.
        block = source.split(f'translation_key="{key}"')[1].split(")")[0]
        for name in placeholders:
            assert f'"{name}"' in block, f"{key} never supplies {{{name}}}"


def test_no_urls_in_user_facing_strings() -> None:
    """hassfest rejects a URL anywhere in strings.json.

    Its reasoning is that a literal address cannot be localised and dates
    badly; the guidance is to use a description placeholder instead. Checked
    here because hassfest only runs in CI, so without this the failure is a
    round trip to GitHub rather than a local test run.
    """
    strings = json.loads(STRINGS.read_text())

    def walk(node: object, path: str = "") -> list[str]:
        if isinstance(node, dict):
            return [
                hit
                for key, value in node.items()
                for hit in walk(value, f"{path}.{key}" if path else key)
            ]
        if isinstance(node, str) and re.search(r"https?://", node):
            return [f"{path}: {node}"]
        return []

    assert not walk(strings)
