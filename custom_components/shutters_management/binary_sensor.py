"""Binary sensor indicating whether a sun-protection group is currently active."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShuttersSunProtectionManager
from .const import DOMAIN, SUBENTRY_TYPE_SUN_PROTECTION, signal_state_update
from .entities import _build_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a binary sensor for every sun-protection subentry of the hub."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SUN_PROTECTION:
            continue
        manager: ShuttersSunProtectionManager = hass.data[DOMAIN][
            subentry.subentry_id
        ]
        async_add_entities(
            [SunProtectionActiveSensor(manager)],
            config_subentry_id=subentry.subentry_id,
        )


class SunProtectionActiveSensor(BinarySensorEntity):
    """True when the sun-protection group is currently lowering covers."""

    _attr_has_entity_name = True
    _attr_translation_key = "sun_protection_active"
    _attr_should_poll = False

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        self._manager = manager
        subentry = manager.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_sun_protection_active"
        suggested = _build_entity_id(
            "binary_sensor", subentry, self._attr_translation_key
        )
        if suggested is not None:
            self.entity_id = suggested
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            manufacturer="Shutters Management",
            entry_type=DeviceEntryType.SERVICE,
            translation_key="sun_protection",
        )

    @property
    def is_on(self) -> bool:
        return self._manager.is_active

    @property
    def extra_state_attributes(self) -> dict:
        data = self._manager.subentry.data
        sun_state = self.hass.states.get("sun.sun")
        elevation = sun_state.attributes.get("elevation") if sun_state else None
        azimuth = sun_state.attributes.get("azimuth") if sun_state else None

        override_until = self._manager.override_until
        return {
            "orientation": data.get("orientation"),
            "arc": data.get("arc"),
            "elevation": elevation,
            "azimuth": azimuth,
            "lux": self._manager.lux,
            "temp_outdoor": self._manager.temp_outdoor,
            "temp_indoor": self._manager.temp_indoor,
            "override_until": (
                override_until.isoformat() if override_until else None
            ),
            "status": self._manager.status,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_state_update(self._manager.subentry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
