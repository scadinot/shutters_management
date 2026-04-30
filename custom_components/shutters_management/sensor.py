"""Timestamp sensors exposing the next scheduled actions."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShuttersScheduler
from .const import DOMAIN, signal_state_update
from .entities import _build_suggested_object_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the next-trigger sensors for a config entry."""
    scheduler: ShuttersScheduler = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ShuttersNextTriggerSensor(scheduler, "open"),
            ShuttersNextTriggerSensor(scheduler, "close"),
        ]
    )


class ShuttersNextTriggerSensor(SensorEntity):
    """Sensor exposing the next scheduled open or close as a timestamp."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False

    def __init__(self, scheduler: ShuttersScheduler, kind: str) -> None:
        self._scheduler = scheduler
        self._kind = kind
        self._attr_unique_id = f"{scheduler.entry.entry_id}_next_{kind}"
        self._attr_translation_key = f"next_{kind}"
        self._attr_suggested_object_id = _build_suggested_object_id(
            scheduler.entry, self._attr_translation_key
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, scheduler.entry.entry_id)},
            name=scheduler.entry.title,
            manufacturer="Shutters Management",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> datetime | None:
        if self._kind == "open":
            return self._scheduler.next_open()
        return self._scheduler.next_close()

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
