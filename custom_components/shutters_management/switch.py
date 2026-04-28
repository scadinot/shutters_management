"""Switch exposing the simulation active/paused state as a toggleable entity."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShuttersScheduler
from .const import DOMAIN, signal_state_update


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the simulation switch for a config entry."""
    scheduler: ShuttersScheduler = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShuttersSimulationSwitch(scheduler)])


class ShuttersSimulationSwitch(SwitchEntity):
    """Switch reflecting and toggling the active/paused state of the simulation."""

    _attr_has_entity_name = True
    _attr_translation_key = "simulation_active"
    _attr_should_poll = False

    def __init__(self, scheduler: ShuttersScheduler) -> None:
        self._scheduler = scheduler
        self._attr_unique_id = f"{scheduler.entry.entry_id}_simulation_active"
        self._attr_suggested_object_id = f"{DOMAIN}_simulation_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, scheduler.entry.entry_id)},
            name="Shutters Management",
            manufacturer="Shutters Management",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return not self._scheduler.paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._scheduler.async_set_paused(False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._scheduler.async_set_paused(True)

    async def async_added_to_hass(self) -> None:
        """Subscribe to state updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_state_update(self._scheduler.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
