"""Buttons that trigger an immediate open or close from the dashboard."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShuttersScheduler
from .const import ACTION_CLOSE, ACTION_OPEN, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the test buttons for a config entry."""
    scheduler: ShuttersScheduler = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ShuttersRunNowButton(scheduler, ACTION_OPEN),
            ShuttersRunNowButton(scheduler, ACTION_CLOSE),
        ]
    )


class ShuttersRunNowButton(ButtonEntity):
    """Button that runs the configured covers immediately."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, scheduler: ShuttersScheduler, action: str) -> None:
        self._scheduler = scheduler
        self._action = action
        self._attr_unique_id = f"{scheduler.entry.entry_id}_test_{action}"
        self._attr_translation_key = f"test_{action}"
        self._attr_suggested_object_id = f"{DOMAIN}_test_{action}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, scheduler.entry.entry_id)},
            name="Shutters Management",
            manufacturer="Shutters Management",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        await self._scheduler.async_run_now(self._action)
