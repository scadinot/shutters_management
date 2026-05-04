"""Timestamp + diagnostic sensors for the Shutters Management integration.

Two families:

* ``ShuttersNextTriggerSensor`` — one ``next_open`` / ``next_close`` per
  schedule subentry (Planification + Simulation de présence).
* ``_SunProtectionDiagnosticSensor`` and its 14 subclasses — diagnostic
  observability on a sun_protection group: status, current adaptive
  thresholds, debounce countdown, override timestamp, mirrored sensor
  readings, and computed margins to help calibrate ``arc`` /
  ``min_elevation`` / ``min_uv``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEGREE,
    LIGHT_LUX,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShuttersScheduler, ShuttersSunProtectionManager
from .const import (
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    DOMAIN,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    signal_state_update,
)
from .entities import _build_entity_id


_STATUS_OPTIONS = [
    "disabled",
    "override",
    "no_sensor",
    "below_horizon",
    "out_of_arc",
    "temp_too_cold",
    "lux_too_low",
    "uv_too_low",
    "room_too_cool",
    "pending_close",
    "active",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register the sensors for every subentry of the hub."""
    for subentry in entry.subentries.values():
        manager = hass.data[DOMAIN].get(subentry.subentry_id)
        if manager is None:
            continue

        if subentry.subentry_type in (
            SUBENTRY_TYPE_INSTANCE,
            SUBENTRY_TYPE_PRESENCE_SIM,
        ):
            async_add_entities(
                [
                    ShuttersNextTriggerSensor(manager, "open"),
                    ShuttersNextTriggerSensor(manager, "close"),
                ],
                config_subentry_id=subentry.subentry_id,
            )
        elif subentry.subentry_type == SUBENTRY_TYPE_SUN_PROTECTION:
            async_add_entities(
                _build_sun_protection_sensors(manager),
                config_subentry_id=subentry.subentry_id,
            )


# ---------------------------------------------------------------------------
# Schedule sensors
# ---------------------------------------------------------------------------


class ShuttersNextTriggerSensor(SensorEntity):
    """Sensor exposing the next scheduled open or close as a timestamp."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False

    def __init__(self, scheduler: ShuttersScheduler, kind: str) -> None:
        self._scheduler = scheduler
        self._kind = kind
        subentry = scheduler.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_next_{kind}"
        self._attr_translation_key = f"next_{kind}"
        suggested = _build_entity_id(
            "sensor", subentry, self._attr_translation_key
        )
        if suggested is not None:
            self.entity_id = suggested
        device_translation_key = (
            "presence_simulation"
            if subentry.subentry_type == SUBENTRY_TYPE_PRESENCE_SIM
            else "instance"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            manufacturer="Shutters Management",
            entry_type=DeviceEntryType.SERVICE,
            translation_key=device_translation_key,
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
                signal_state_update(self._scheduler.subentry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Sun-protection diagnostic sensors
# ---------------------------------------------------------------------------


def _build_sun_protection_sensors(
    manager: ShuttersSunProtectionManager,
) -> list[SensorEntity]:
    """Return the 14 diagnostic sensors for a sun_protection group."""
    return [
        SunProtectionStatusSensor(manager),
        SunProtectionLuxThresholdSensor(manager),
        SunProtectionPendingSensor(manager),
        SunProtectionOverrideUntilSensor(manager),
        SunProtectionAzimuthSensor(manager),
        SunProtectionElevationSensor(manager),
        SunProtectionLuxSensor(manager),
        SunProtectionUVSensor(manager),
        SunProtectionTempOutdoorSensor(manager),
        SunProtectionTempIndoorSensor(manager),
        SunProtectionAzimuthDiffSensor(manager),
        SunProtectionElevationMarginSensor(manager),
        SunProtectionLuxMarginSensor(manager),
        SunProtectionUVMarginSensor(manager),
    ]


class _SunProtectionDiagnosticSensor(SensorEntity):
    """Common boilerplate: device info, dispatcher subscription, name slug."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        manager: ShuttersSunProtectionManager,
        translation_key: str,
    ) -> None:
        self._manager = manager
        subentry = manager.subentry
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{subentry.subentry_id}_{translation_key}"
        suggested = _build_entity_id("sensor", subentry, translation_key)
        if suggested is not None:
            self.entity_id = suggested
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            manufacturer="Shutters Management",
            entry_type=DeviceEntryType.SERVICE,
            translation_key="sun_protection",
        )

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


class SunProtectionStatusSensor(_SunProtectionDiagnosticSensor):
    """Translated status string from ``manager.status``."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_STATUS_OPTIONS)

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_status")

    @property
    def native_value(self) -> str:
        return self._manager.status


class SunProtectionLuxThresholdSensor(_SunProtectionDiagnosticSensor):
    """Adaptive close lux threshold currently in effect."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_lux_threshold")

    @property
    def native_value(self) -> int | None:
        return self._manager.lux_close_threshold


class SunProtectionPendingSensor(_SunProtectionDiagnosticSensor):
    """Seconds remaining in the close or open debounce window."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_pending_seconds")

    @property
    def native_value(self) -> int:
        return self._manager.pending_seconds


class SunProtectionOverrideUntilSensor(_SunProtectionDiagnosticSensor):
    """Timestamp of the next override reset, ``None`` when no override."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_override_until")

    @property
    def native_value(self) -> datetime | None:
        return self._manager.override_until


class SunProtectionAzimuthSensor(_SunProtectionDiagnosticSensor):
    """Mirror of ``sun.sun`` azimuth, scoped to the device card."""

    _attr_native_unit_of_measurement = DEGREE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_sun_azimuth")

    @property
    def native_value(self) -> float | None:
        return self._manager.azimuth


class SunProtectionElevationSensor(_SunProtectionDiagnosticSensor):
    """Mirror of ``sun.sun`` elevation."""

    _attr_native_unit_of_measurement = DEGREE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_sun_elevation")

    @property
    def native_value(self) -> float | None:
        return self._manager.elevation


class SunProtectionLuxSensor(_SunProtectionDiagnosticSensor):
    """Mirror of the configured outdoor lux sensor."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_lux")

    @property
    def native_value(self) -> float | None:
        return self._manager.lux


class SunProtectionUVSensor(_SunProtectionDiagnosticSensor):
    """Mirror of the configured UV index sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_uv_index")

    @property
    def native_value(self) -> float | None:
        return self._manager.uv


class SunProtectionTempOutdoorSensor(_SunProtectionDiagnosticSensor):
    """Mirror of the configured outdoor temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_temp_outdoor")

    @property
    def native_value(self) -> float | None:
        return self._manager.temp_outdoor


class SunProtectionTempIndoorSensor(_SunProtectionDiagnosticSensor):
    """Mirror of the per-group room temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_temp_indoor")

    @property
    def native_value(self) -> float | None:
        return self._manager.temp_indoor


class SunProtectionAzimuthDiffSensor(_SunProtectionDiagnosticSensor):
    """Absolute angular distance between sun azimuth and orientation."""

    _attr_native_unit_of_measurement = DEGREE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_azimuth_diff")

    @property
    def native_value(self) -> float | None:
        return self._manager.azimuth_diff


class SunProtectionElevationMarginSensor(_SunProtectionDiagnosticSensor):
    """``elevation − min_elevation`` (negative when sun too low)."""

    _attr_native_unit_of_measurement = DEGREE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_elevation_margin")

    @property
    def native_value(self) -> float | None:
        elev = self._manager.elevation
        if elev is None:
            return None
        min_el = self._manager.subentry.data.get(
            CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION
        )
        return elev - float(min_el)


class SunProtectionLuxMarginSensor(_SunProtectionDiagnosticSensor):
    """``lux − close_threshold`` (negative when below the close threshold)."""

    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_lux_margin")

    @property
    def native_value(self) -> float | None:
        lux = self._manager.lux
        threshold = self._manager.lux_close_threshold
        if lux is None or threshold is None:
            return None
        return lux - threshold


class SunProtectionUVMarginSensor(_SunProtectionDiagnosticSensor):
    """``uv − min_uv`` (negative when UV insufficient)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: ShuttersSunProtectionManager) -> None:
        super().__init__(manager, "sun_protection_uv_margin")

    @property
    def native_value(self) -> float | None:
        uv = self._manager.uv
        if uv is None:
            return None
        min_uv = float(
            self._manager.subentry.data.get(CONF_MIN_UV, DEFAULT_MIN_UV)
        )
        return uv - min_uv
