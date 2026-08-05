"""Tests for setting up and tearing down the Mempool integration."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mempool.const import (
    API_PRICES,
    API_TIP_HEIGHT,
    CONF_BASE_URL,
    CONF_CURRENCY,
    CONF_FAST_INTERVAL,
    DOMAIN,
    SERVICE_IMPORT_PRICE_HISTORY,
)
from custom_components.mempool.sensor import SENSORS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import BASE_URL


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A healthy instance loads every sensor and unloads cleanly."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    runtime = mock_config_entry.runtime_data
    assert runtime.price is not None
    assert runtime.currency == "USD"

    # Every described sensor, plus the price sensor.
    entities = hass.states.async_entity_ids("sensor")
    assert len(entities) == len(SENSORS) + 1

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    # Unloading leaves the entities registered but with no live value.
    assert all(
        hass.states.get(entity_id).state == STATE_UNAVAILABLE
        for entity_id in hass.states.async_entity_ids("sensor")
    )


async def test_setup_creates_one_device(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """One device per config entry, pointing back at the instance."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, mock_config_entry.entry_id)}
    assert devices[0].configuration_url == BASE_URL


async def test_setup_retries_when_unreachable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unreachable instance leaves the entry in retry, not failed."""
    aioclient_mock.get(f"{BASE_URL}{API_PRICES}", status=500)
    aioclient_mock.get(f"{BASE_URL}{API_TIP_HEIGHT}", status=500)

    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_without_price_feed(
    hass: HomeAssistant,
    mock_api_no_price: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing price feed is a warning, not a setup failure."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.price is None
    assert len(hass.states.async_entity_ids("sensor")) == len(SENSORS)
    assert "price sensor disabled" in caplog.text


async def test_setup_when_currency_not_served(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A price feed that lacks the chosen fiat also disables the price sensor."""
    from .conftest import mock_endpoints

    mock_endpoints(aioclient_mock, prices={"time": 1, "EUR": 88000})
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.price is None
    assert "price sensor disabled" in caplog.text


async def test_setup_without_currency_skips_price_probe(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
) -> None:
    """No configured currency means no price coordinator at all."""
    from .conftest import BASE_URL as URL

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=URL,
        data={"base_url": URL, "verify_ssl": True, CONF_FAST_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.price is None
    assert entry.runtime_data.currency is None


async def test_options_update_reloads_entry(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Changing an option rebuilds the coordinators with the new interval."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_FAST_INTERVAL: 300, CONF_CURRENCY: "AUD"}
    )
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.currency == "AUD"
    assert mock_config_entry.runtime_data.fast.update_interval.total_seconds() == 300


async def test_service_registered_on_setup(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The import action is available once the integration is set up."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_IMPORT_PRICE_HISTORY)


async def test_service_registered_even_when_entry_fails_to_load(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Actions are registered in async_setup, so they survive a failed entry.

    This is the point of the action-setup rule: automations that call the
    action can still be validated when no entry is loaded.
    """
    aioclient_mock.get(f"{BASE_URL}{API_PRICES}", status=500)
    aioclient_mock.get(f"{BASE_URL}{API_TIP_HEIGHT}", status=500)

    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.services.has_service(DOMAIN, SERVICE_IMPORT_PRICE_HISTORY)


async def test_service_survives_unload(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Unloading the last entry does not deregister the global action."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_IMPORT_PRICE_HISTORY)


async def test_device_model_reflects_the_instance_kind(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """The device model says which kind of instance the entry talks to."""
    from .conftest import PUBLIC_URL, mock_endpoints

    mock_endpoints(aioclient_mock)
    mock_endpoints(aioclient_mock, PUBLIC_URL)

    self_hosted = MockConfigEntry(
        domain=DOMAIN,
        unique_id=BASE_URL,
        data={CONF_BASE_URL: BASE_URL, CONF_FAST_INTERVAL: 60},
    )
    public = MockConfigEntry(
        domain=DOMAIN,
        unique_id=PUBLIC_URL,
        data={CONF_BASE_URL: PUBLIC_URL, CONF_FAST_INTERVAL: 300},
    )

    models = {}
    for entry in (self_hosted, public):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        device = dr.async_entries_for_config_entry(device_registry, entry.entry_id)[0]
        models[entry.data[CONF_BASE_URL]] = device.model

    assert models[PUBLIC_URL] == "mempool.space"
    assert models[BASE_URL] == "Self-hosted mempool"
