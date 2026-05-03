"""Base entity for EnergyFacts integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class EnergyFactsEntity(CoordinatorEntity):
    """Base class for EnergyFacts entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str, key: str, name: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_name = name
        self._entry_id = entry_id
        self._key = key

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="EnergyFacts",
            manufacturer="EnergyFacts",
            entry_type=DeviceEntryType.SERVICE,
        )
