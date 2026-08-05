"""Base entity for the Mempool integration.

Holds everything that is true of any entity backed by a mempool instance —
the device it belongs to, its unique ID and the has-entity-name convention —
so entity platforms only carry their own specifics.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import CONF_BASE_URL, DOMAIN, MEMPOOL_SPACE_URL
from .coordinator import MempoolConfigEntry


class MempoolEntity(CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]]):
    """An entity reading from one of a config entry's coordinators."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry: MempoolConfigEntry,
        unique_suffix: str,
    ) -> None:
        """Bind the entity to its coordinator, config entry and device."""
        super().__init__(coordinator)
        # Unique IDs are live in real installations and carry months of
        # recorded history. Neither this composition nor the suffixes callers
        # pass in may change: doing so silently orphans that history.
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        base_url = entry.data[CONF_BASE_URL]
        # One device per config entry (the instance); all entities group under it.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="mempool",
            # Which kind of instance this entry actually talks to. Model is
            # display metadata, not part of the device identity.
            model=(
                "mempool.space"
                if base_url == MEMPOOL_SPACE_URL
                else "Self-hosted mempool"
            ),
            configuration_url=base_url,
        )
