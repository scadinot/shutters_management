"""Binary sensor exposing the simulation active/paused state."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShuttersScheduler
from .const import DOMAIN, SIGNAL_STATE_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the active/paused binary sensor for a config entry."""
    scheduler: ShuttersScheduler = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShuttersActiveBinarySensor(scheduler)])


class ShuttersActiveBinarySensor(BinarySensorEntity):
    """Binary sensor reflecting whether the simulation is currently active."""

    _attr_has_entity_name = True
    _attr_translation_key = "active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_should_poll = False

    def __init__(self, scheduler: ShuttersScheduler) -> None:
        self._scheduler = scheduler
        self._attr_unique_id = f"{scheduler.entry.entry_id}_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, scheduler.entry.entry_id)},
            name="Shutters Management",
            manufacturer="Shutters Management",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return not self._scheduler.paused

    async def async_added_to_hass(self) -> None:
        """Subscribe to state updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_STATE_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
