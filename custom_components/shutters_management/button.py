"""Buttons that trigger an immediate open or close from the dashboard."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShuttersScheduler
from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    DEVICE_MODEL_INSTANCE,
    DOMAIN,
    SUBENTRY_TYPE_INSTANCE,
)
from .entities import _build_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the test buttons for every instance subentry of the hub."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_INSTANCE:
            continue
        scheduler: ShuttersScheduler = hass.data[DOMAIN][subentry.subentry_id]
        async_add_entities(
            [
                ShuttersRunNowButton(scheduler, ACTION_OPEN),
                ShuttersRunNowButton(scheduler, ACTION_CLOSE),
            ],
            config_subentry_id=subentry.subentry_id,
        )


class ShuttersRunNowButton(ButtonEntity):
    """Button that runs the configured covers immediately."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, scheduler: ShuttersScheduler, action: str) -> None:
        self._scheduler = scheduler
        self._action = action
        subentry = scheduler.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_test_{action}"
        self._attr_translation_key = f"test_{action}"
        suggested = _build_entity_id(
            "button", subentry, self._attr_translation_key
        )
        if suggested is not None:
            self.entity_id = suggested
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Shutters Management",
            model=DEVICE_MODEL_INSTANCE,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        await self._scheduler.async_run_now(self._action)
