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
from .const import DOMAIN, SUBENTRY_TYPE_INSTANCE, signal_state_update
from .entities import _build_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the simulation switch for every instance subentry of the hub."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_INSTANCE:
            continue
        scheduler: ShuttersScheduler = hass.data[DOMAIN][subentry.subentry_id]
        async_add_entities(
            [ShuttersSimulationSwitch(scheduler)],
            config_subentry_id=subentry.subentry_id,
        )


class ShuttersSimulationSwitch(SwitchEntity):
    """Switch reflecting and toggling the active/paused state of the simulation."""

    _attr_has_entity_name = True
    _attr_translation_key = "simulation_active"
    _attr_should_poll = False

    def __init__(self, scheduler: ShuttersScheduler) -> None:
        self._scheduler = scheduler
        subentry = scheduler.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_simulation_active"
        suggested = _build_entity_id(
            "switch", subentry, self._attr_translation_key
        )
        if suggested is not None:
            self.entity_id = suggested
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
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
                signal_state_update(self._scheduler.subentry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
