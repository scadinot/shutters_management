"""Shutters Management integration."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
from types import MappingProxyType
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    STATE_CLOSED,
    STATE_OPEN,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_sunrise,
    async_track_sunset,
    async_track_time_change,
)
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    ATTR_ACTION,
    AWAY_STATES,
    CONF_CLOSE_MODE,
    CONF_CLOSE_OFFSET,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_WHEN_AWAY_ONLY,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_MODE,
    CONF_OPEN_OFFSET,
    CONF_OPEN_TIME,
    CONF_PRESENCE_ENTITY,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_SEQUENTIAL_COVERS,
    CONF_TTS_ENGINE,
    CONF_TTS_MODE,
    CONF_TTS_TARGETS,
    CONF_TTS_WHEN_AWAY_ONLY,
    CONF_TYPE,
    COVER_ACTION_TIMEOUT_SECONDS,
    DAYS,
    DEFAULT_CLOSE_MODE,
    DEFAULT_CLOSE_OFFSET,
    DEFAULT_NOTIFY_MODE,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_OPEN_MODE,
    DEFAULT_OPEN_OFFSET,
    DEFAULT_RANDOM_MAX_MINUTES,
    DEFAULT_SEQUENTIAL_COVERS,
    DEFAULT_TTS_MODE,
    DEFAULT_TTS_TARGETS,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    MODE_ALWAYS,
    MODE_AWAY_ONLY,
    MODE_DISABLED,
    MODE_FIXED,
    MODE_NONE,
    MODE_SUNRISE,
    MODE_SUNSET,
    PLATFORMS,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_RUN_NOW,
    CONF_ARC,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_ORIENTATION,
    CONF_TARGET_POSITION,
    CONF_UV_ENTITY,
    DEFAULT_ARC,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    DEFAULT_TARGET_POSITION,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    SUN_ENTITY,
    TRIGGER_MODES,
    TYPE_HUB,
    signal_state_update,
)

_LOGGER = logging.getLogger(__name__)

# Stale `DeviceInfo.model` values defined in v0.4.8/v0.4.9 and removed in v0.4.10.
# Persisted in the device registry until explicitly cleared (HA does not clean
# up fields removed from DeviceInfo). Used by the one-time migration in
# `async_setup_entry`.
_RESIDUAL_DEVICE_MODELS = frozenset({"Presence schedule", "Sun protection"})

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RUN_NOW_SCHEMA = vol.Schema(
    {vol.Required(ATTR_ACTION): vol.In([ACTION_OPEN, ACTION_CLOSE])}
)


_NOTIFY_HEADERS: dict[str, dict[str, str]] = {
    "fr": {
        ACTION_OPEN: "Volets ouverts :",
        ACTION_CLOSE: "Volets fermés :",
    },
    "en": {
        ACTION_OPEN: "Shutters opened:",
        ACTION_CLOSE: "Shutters closed:",
    },
}


_TTS_HEADERS: dict[str, dict[str, str]] = {
    "fr": {
        # French typography: space before the colon.
        ACTION_OPEN: "Volets ouverts : ",
        ACTION_CLOSE: "Volets fermés : ",
    },
    "en": {
        ACTION_OPEN: "Shutters opened: ",
        ACTION_CLOSE: "Shutters closed: ",
    },
}


def _cover_display_name(hass: HomeAssistant, entity_id: str) -> str:
    """Friendly_name for ``entity_id`` when known, raw entity_id otherwise."""
    state = hass.states.get(entity_id)
    if state is None:
        return entity_id
    return state.attributes.get("friendly_name") or entity_id


def _notify_message(
    hass: HomeAssistant, language: str, action: str, processed_covers: list[str]
) -> str:
    """Build the localized notification body.

    The body lists each cover in **processing order** — i.e. the order
    in which the scheduler actually fired ``cover.<service>`` (the
    shuffled order in sequential mode, the configuration order in
    batched mode). Each cover is rendered using its ``friendly_name``
    when available, with the ``entity_id`` as a fallback.
    """
    bucket = _NOTIFY_HEADERS.get(language, _NOTIFY_HEADERS["en"])
    header = bucket.get(action, _NOTIFY_HEADERS["en"][action])
    lines = [header]
    for entity_id in processed_covers:
        lines.append(_cover_display_name(hass, entity_id))
    return "\n".join(lines)


def _tts_message(
    hass: HomeAssistant, language: str, action: str, processed_covers: list[str]
) -> str:
    """Build the spoken-announcement body for ``tts.speak``.

    Same content as ``_notify_message`` but joined with commas instead
    of newlines, so a smart speaker reads a natural sentence rather
    than a string of awkward pauses on each line break:
    ``"Shutters opened: Living Room, Kitchen, Bedroom."``. The header
    already carries its own ``: `` (or `` : `` in French) so the join
    is unconditional.
    """
    bucket = _TTS_HEADERS.get(language, _TTS_HEADERS["en"])
    header = bucket.get(action, _TTS_HEADERS["en"][action])
    names = [_cover_display_name(hass, entity_id) for entity_id in processed_covers]
    return f"{header}{', '.join(names)}."


def _parse_time(value: str | time) -> time:
    """Parse a HH:MM(:SS) string into a time object."""
    if isinstance(value, time):
        return value
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


def _next_datetime_for(
    local_now: datetime, time_value: time, days_keys: list[str]
) -> datetime | None:
    """Return the next datetime matching time_value on an active weekday."""
    candidate = local_now.replace(
        hour=time_value.hour,
        minute=time_value.minute,
        second=time_value.second,
        microsecond=0,
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    for _ in range(8):
        if DAYS[candidate.weekday()] in days_keys:
            return candidate
        candidate += timedelta(days=1)
    return None


def _strip_name(data: dict[str, Any]) -> dict[str, Any]:
    """Drop CONF_NAME from a payload destined to ``ConfigSubentry.data``."""
    return {k: v for k, v in data.items() if k != CONF_NAME}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (YAML not supported).

    Pre-v0.4.0 entries are migrated here, before per-entry setup runs:
    legacy single-instance entries are folded into a single hub entry as
    subentries. This must happen in ``async_setup`` rather than
    ``async_migrate_entry`` because the migration creates / deletes
    sibling entries — operations that would race if performed
    per-entry during their individual migration step.
    """
    hass.data.setdefault(DOMAIN, {})
    await _async_migrate_legacy_entries(hass)
    return True


async def _async_migrate_legacy_entries(hass: HomeAssistant) -> None:
    """Promote any v2 legacy entries to subentries of a hub entry."""
    all_entries = hass.config_entries.async_entries(DOMAIN)
    legacy = [e for e in all_entries if e.version < 3]
    if not legacy:
        return

    hub = next(
        (e for e in all_entries if e.data.get(CONF_TYPE) == TYPE_HUB),
        None,
    )

    if hub is None:
        # Promote the first legacy entry into the hub itself, keeping its
        # original instance configuration as the first subentry. The new
        # subentry reuses the legacy ``entry.entry_id`` as its
        # ``subentry_id`` so existing entity unique_ids
        # (``f"{entry.entry_id}_next_open"``, etc.) keep matching after
        # the move — HA finds the registry entry by unique_id and
        # updates ``config_subentry_id`` in place rather than creating
        # a duplicate.
        seed = legacy.pop(0)
        original_data = dict(seed.data)
        original_options = dict(seed.options)
        instance_data = _strip_name({**original_data, **original_options})
        instance_title = seed.title or original_data.get(CONF_NAME) or HUB_TITLE
        instance_unique_id = seed.unique_id
        legacy_id = seed.entry_id

        hass.config_entries.async_update_entry(
            seed,
            title=HUB_TITLE,
            data={
                CONF_TYPE: TYPE_HUB,
                CONF_NOTIFY_SERVICES: DEFAULT_NOTIFY_SERVICES,
                CONF_NOTIFY_WHEN_AWAY_ONLY: False,
            },
            options={},
            unique_id=HUB_UNIQUE_ID,
            version=3,
        )
        hass.config_entries.async_add_subentry(
            seed,
            ConfigSubentry(
                subentry_id=legacy_id,
                subentry_type=SUBENTRY_TYPE_INSTANCE,
                title=instance_title,
                unique_id=instance_unique_id,
                data=MappingProxyType(instance_data),
            ),
        )
        hub = seed
        _LOGGER.info(
            "Migrated legacy entry %s to hub with first subentry %s",
            seed.entry_id,
            instance_title,
        )

    for entry in legacy:
        # Same trick: reuse the legacy entry_id as subentry_id so the
        # entity registry can re-bind by unique_id once the legacy
        # entry is gone.
        instance_data = _strip_name({**entry.data, **entry.options})
        instance_title = entry.title or entry.data.get(CONF_NAME) or "Instance"
        hass.config_entries.async_add_subentry(
            hub,
            ConfigSubentry(
                subentry_id=entry.entry_id,
                subentry_type=SUBENTRY_TYPE_INSTANCE,
                title=instance_title,
                unique_id=entry.unique_id,
                data=MappingProxyType(instance_data),
            ),
        )
        await hass.config_entries.async_remove(entry.entry_id)
        _LOGGER.info(
            "Migrated legacy entry %s into hub subentry %s",
            entry.entry_id,
            instance_title,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the hub entry: spawn one scheduler per subentry."""
    hass.data.setdefault(DOMAIN, {})

    if entry.data.get(CONF_TYPE) != TYPE_HUB:
        # Defensive guard: any entry that did not get migrated to the
        # hub model is not loadable in v0.4.0+.
        _LOGGER.error(
            "Entry %s is not a hub (type=%s); refusing to load",
            entry.entry_id,
            entry.data.get(CONF_TYPE),
        )
        return False

    # One-time cleanup: clear the residual `model` field cached in the device
    # registry from v0.4.8/v0.4.9 (removed in v0.4.10, but persisted on
    # existing devices). Constrained to the two known stale values so that
    # any future legitimate `model` set by this integration is preserved.
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if device.model in _RESIDUAL_DEVICE_MODELS:
            device_registry.async_update_device(device.id, model=None)

    for subentry in entry.subentries.values():
        if subentry.subentry_type in (SUBENTRY_TYPE_INSTANCE, SUBENTRY_TYPE_PRESENCE_SIM):
            scheduler = ShuttersScheduler(hass, entry, subentry)
            scheduler.async_schedule()
            hass.data[DOMAIN][subentry.subentry_id] = scheduler
        elif subentry.subentry_type == SUBENTRY_TYPE_SUN_PROTECTION:
            manager = ShuttersSunProtectionManager(hass, entry, subentry)
            await manager.async_setup()
            hass.data[DOMAIN][subentry.subentry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a hub entry and tear down all of its subentry schedulers."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    for subentry in entry.subentries.values():
        manager = hass.data.get(DOMAIN, {}).pop(subentry.subentry_id, None)
        if manager is None:
            continue
        if isinstance(manager, ShuttersScheduler):
            manager.async_unschedule()
        elif isinstance(manager, ShuttersSunProtectionManager):
            await manager.async_unload()

    if not hass.data.get(DOMAIN):
        _async_unregister_services(hass)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only when the set of instance subentries actually changed.

    The hub options flow rewrites ``entry.data`` to update the shared
    notification settings, which would otherwise trigger a reload here.
    But notifications already re-read ``hub_entry.data`` on every send,
    so a reload is just churn (entities flicker, schedulers respawn).

    The listener still fires on subentry add / remove / reconfigure
    because those changes mutate ``entry.subentries``; in that case we
    do reload so the per-subentry schedulers and entity lists are
    rebuilt.
    """
    current = {
        sub.subentry_id: dict(sub.data)
        for sub in entry.subentries.values()
        if sub.subentry_type in (
            SUBENTRY_TYPE_INSTANCE,
            SUBENTRY_TYPE_PRESENCE_SIM,
            SUBENTRY_TYPE_SUN_PROTECTION,
        )
    }
    loaded = {
        sid: dict(mgr.subentry.data)
        for sid, mgr in hass.data.get(DOMAIN, {}).items()
        if mgr.hub_entry is entry
    }
    if current == loaded:
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Migrate older config entries forward.

    The actual v2→v3 conversion (hub + subentries promotion) happens in
    :func:`_async_migrate_legacy_entries` during ``async_setup``. By the
    time HA calls ``async_migrate_entry`` the entry is either already at
    v3+ (ready) or failed migration (we refuse and let the user notice).

    v3→v4: Replace the two boolean ``*_when_away_only`` flags with a
    three-state mode constant (``disabled`` / ``always`` / ``away_only``)
    on each notification channel.

    v4→v5: Split the former ``instance`` subentry into a deterministic
    ``Planification`` (still ``subentry_type='instance'``) and a new
    ``presence_simulation`` type. Existing ``instance`` subentries are
    kept as Planification, with the now-irrelevant simulation fields
    purged from their ``data``.
    """
    if entry.version < 3:
        _LOGGER.warning(
            "Entry %s is still at version %s after pre-setup migration; refusing to load",
            entry.entry_id,
            entry.version,
        )
        return False

    if entry.version < 4:
        data = dict(entry.data)

        if CONF_NOTIFY_MODE not in data:
            services = data.get(CONF_NOTIFY_SERVICES, [])
            away_only = data.pop(CONF_NOTIFY_WHEN_AWAY_ONLY, False)
            if not services:
                data[CONF_NOTIFY_MODE] = MODE_DISABLED
            elif away_only:
                data[CONF_NOTIFY_MODE] = MODE_AWAY_ONLY
            else:
                data[CONF_NOTIFY_MODE] = MODE_ALWAYS

        if CONF_TTS_MODE not in data:
            engine = data.get(CONF_TTS_ENGINE)
            tts_targets = data.get(CONF_TTS_TARGETS, [])
            tts_away_only = data.pop(CONF_TTS_WHEN_AWAY_ONLY, False)
            if not engine or not tts_targets:
                data[CONF_TTS_MODE] = MODE_DISABLED
            elif tts_away_only:
                data[CONF_TTS_MODE] = MODE_AWAY_ONLY
            else:
                data[CONF_TTS_MODE] = MODE_ALWAYS

        hass.config_entries.async_update_entry(entry, data=data, version=4)
        _LOGGER.info("Migrated entry %s from version 3 to 4", entry.entry_id)

    if entry.version < 5:
        _PRESENCE_SIM_FIELDS = (
            CONF_RANDOMIZE,
            CONF_RANDOM_MAX_MINUTES,
            CONF_ONLY_WHEN_AWAY,
            CONF_PRESENCE_ENTITY,
        )
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_INSTANCE:
                continue
            stripped = {
                k: v for k, v in subentry.data.items()
                if k not in _PRESENCE_SIM_FIELDS
            }
            if stripped != dict(subentry.data):
                hass.config_entries.async_update_subentry(
                    entry, subentry, data=stripped
                )
        hass.config_entries.async_update_entry(entry, version=5)
        _LOGGER.info("Migrated entry %s from version 4 to 5", entry.entry_id)

    return True


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        return

    async def _handle_run_now(call: ServiceCall) -> None:
        action = call.data[ATTR_ACTION]
        for manager in list(hass.data.get(DOMAIN, {}).values()):
            await manager.async_run_now(action)

    async def _handle_pause(call: ServiceCall) -> None:
        for manager in list(hass.data.get(DOMAIN, {}).values()):
            await manager.async_set_paused(True)

    async def _handle_resume(call: ServiceCall) -> None:
        for manager in list(hass.data.get(DOMAIN, {}).values()):
            await manager.async_set_paused(False)

    hass.services.async_register(
        DOMAIN, SERVICE_RUN_NOW, _handle_run_now, schema=RUN_NOW_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_PAUSE, _handle_pause)
    hass.services.async_register(DOMAIN, SERVICE_RESUME, _handle_resume)


@callback
def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration-level services."""
    for service in (SERVICE_RUN_NOW, SERVICE_PAUSE, SERVICE_RESUME):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


class ShuttersSunProtectionManager:
    """Manage sun-position-based shutter lowering for one orientation group."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub_entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        self.hass = hass
        self.hub_entry = hub_entry
        self.subentry = subentry
        self._enabled = True
        self._in_sun_mode = False
        self._snapshots: dict[str, int] = {}
        self._applied_positions: dict[str, int] = {}
        self._unsubs: list[Callable[[], None]] = []

    @property
    def subentry_id(self) -> str:
        return self.subentry.subentry_id

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_active(self) -> bool:
        return self._in_sun_mode and self._enabled

    @property
    def status(self) -> str:
        if not self._enabled:
            return "disabled"
        sun_state = self.hass.states.get(SUN_ENTITY)
        if sun_state is None:
            return "below_horizon"
        elevation = sun_state.attributes.get("elevation", 0)
        azimuth = sun_state.attributes.get("azimuth", 0)
        data = self.subentry.data
        if elevation < data.get(CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION):
            return "below_horizon"
        orientation = data.get(CONF_ORIENTATION, 180)
        arc = data.get(CONF_ARC, DEFAULT_ARC)
        diff = abs((azimuth - orientation + 180) % 360 - 180)
        if diff > arc:
            return "out_of_arc"
        uv_entity = self.hub_entry.data.get(CONF_UV_ENTITY, "")
        if uv_entity:
            uv_state = self.hass.states.get(uv_entity)
            try:
                uv_value = float(uv_state.state) if uv_state else 0.0
            except (ValueError, TypeError):
                uv_value = 0.0
            if uv_value < data.get(CONF_MIN_UV, DEFAULT_MIN_UV):
                return "uv_too_low"
        return "active"

    async def async_setup(self) -> None:
        """Subscribe to sun and UV state changes and run an initial evaluation."""
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [SUN_ENTITY], self._async_on_state_change
            )
        )
        uv_entity = self.hub_entry.data.get(CONF_UV_ENTITY, "")
        if uv_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [uv_entity], self._async_on_state_change
                )
            )
        covers = list(self.subentry.data.get(CONF_COVERS, []))
        if covers:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, covers, self._async_on_cover_state_change
                )
            )
        self._unsubs.append(
            async_call_later(self.hass, 0, self._async_evaluate_cb)
        )

    async def async_unload(self) -> None:
        """Cancel subscriptions and restore positions if in sun mode."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._in_sun_mode:
            await self._async_exit_sun_mode()

    async def _async_on_state_change(self, event: Any) -> None:
        await self.async_evaluate()

    async def _async_evaluate_cb(self, _now: Any) -> None:
        await self.async_evaluate()

    async def async_evaluate(self) -> None:
        """Recompute whether sun protection should be active and act accordingly."""
        if not self._enabled:
            if self._in_sun_mode:
                await self._async_exit_sun_mode()
            return

        sun_state = self.hass.states.get(SUN_ENTITY)
        if sun_state is None:
            return

        elevation = sun_state.attributes.get("elevation", 0)
        azimuth = sun_state.attributes.get("azimuth", 0)
        data = self.subentry.data
        min_elevation = data.get(CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION)
        orientation = data.get(CONF_ORIENTATION, 180)
        arc = data.get(CONF_ARC, DEFAULT_ARC)
        min_uv = data.get(CONF_MIN_UV, DEFAULT_MIN_UV)

        uv_ok = True
        uv_entity = self.hub_entry.data.get(CONF_UV_ENTITY, "")
        if uv_entity:
            uv_state = self.hass.states.get(uv_entity)
            try:
                uv_value = float(uv_state.state) if uv_state else 0.0
            except (ValueError, TypeError):
                uv_value = 0.0
            uv_ok = uv_value >= min_uv

        diff = abs((azimuth - orientation + 180) % 360 - 180)
        should_activate = elevation >= min_elevation and diff <= arc and uv_ok

        if should_activate and not self._in_sun_mode:
            await self._async_enter_sun_mode()
        elif not should_activate and self._in_sun_mode:
            await self._async_exit_sun_mode()

        async_dispatcher_send(self.hass, signal_state_update(self.subentry_id))

    async def _async_enter_sun_mode(self) -> None:
        """Snapshot current positions and lower covers to target."""
        covers = list(self.subentry.data.get(CONF_COVERS, []))
        target = self.subentry.data.get(CONF_TARGET_POSITION, DEFAULT_TARGET_POSITION)

        for cover_id in covers:
            state = self.hass.states.get(cover_id)
            if state is not None:
                pos = state.attributes.get("current_position")
                if pos is not None:
                    self._snapshots[cover_id] = int(pos)
            await self.hass.services.async_call(
                "cover",
                "set_cover_position",
                {"entity_id": cover_id, "position": target},
            )
            self._applied_positions[cover_id] = target

        self._in_sun_mode = True
        _LOGGER.debug(
            "Sun protection %s: entered sun mode (target=%s%%)",
            self.subentry_id,
            target,
        )

    async def _async_exit_sun_mode(self) -> None:
        """Restore cover positions, skipping any that were manually moved."""
        covers = list(self.subentry.data.get(CONF_COVERS, []))

        for cover_id in covers:
            applied = self._applied_positions.get(cover_id)
            snapshot = self._snapshots.get(cover_id)
            if snapshot is None:
                continue
            state = self.hass.states.get(cover_id)
            current_pos = None
            if state is not None:
                raw = state.attributes.get("current_position")
                if raw is not None:
                    current_pos = int(raw)
            # Only restore if the cover hasn't been moved manually.
            if current_pos is None or current_pos == applied:
                await self.hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    {"entity_id": cover_id, "position": snapshot},
                )

        self._in_sun_mode = False
        self._snapshots.clear()
        self._applied_positions.clear()
        _LOGGER.debug("Sun protection %s: exited sun mode", self.subentry_id)

    async def _async_on_cover_state_change(self, event: Any) -> None:
        """Update snapshot when a cover we control is moved externally."""
        if not self._in_sun_mode:
            return
        cover_id = event.data.get("entity_id")
        if cover_id not in self._applied_positions:
            return
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        new_pos = new_state.attributes.get("current_position")
        if new_pos is None:
            return
        new_pos_int = int(new_pos)
        applied = self._applied_positions.get(cover_id)
        snapshot = self._snapshots.get(cover_id)
        # Ignore intermediate positions while the cover is moving toward our target.
        # Only consider it an external move when it lands outside the transit range.
        if (
            applied is not None
            and snapshot is not None
            and min(snapshot, applied) <= new_pos_int <= max(snapshot, applied)
        ):
            return
        self._snapshots[cover_id] = new_pos_int
        self._applied_positions[cover_id] = new_pos_int

    def set_enabled(self, enabled: bool) -> None:
        """Toggle the group on/off (called by the switch entity)."""
        self._enabled = enabled
        self.hass.async_create_task(self.async_evaluate())


class ShuttersScheduler:
    """Schedule open/close actions for one instance subentry."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub_entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        self.hass = hass
        self.hub_entry = hub_entry
        self.subentry = subentry
        self.paused = False
        self._unsubs: list[Callable[[], None]] = []
        self._pending_unsubs: list[Callable[[], None]] = []

    @property
    def subentry_id(self) -> str:
        return self.subentry.subentry_id

    @property
    def _settings(self) -> dict[str, Any]:
        data = dict(self.subentry.data)
        # Plain "Planification" (instance) ignores presence-simulation fields
        # even if leftover values exist in storage from a pre-v0.5.0 install.
        if self.subentry.subentry_type == SUBENTRY_TYPE_INSTANCE:
            for key in (
                CONF_RANDOMIZE,
                CONF_RANDOM_MAX_MINUTES,
                CONF_ONLY_WHEN_AWAY,
                CONF_PRESENCE_ENTITY,
            ):
                data.pop(key, None)
        return data

    @callback
    def async_schedule(self) -> None:
        """Register the time triggers based on each event's mode."""
        settings = self._settings

        open_mode = self._resolve_mode(
            settings.get(CONF_OPEN_MODE, DEFAULT_OPEN_MODE),
            DEFAULT_OPEN_MODE,
            f"{SERVICE_OPEN_COVER} mode",
        )
        close_mode = self._resolve_mode(
            settings.get(CONF_CLOSE_MODE, DEFAULT_CLOSE_MODE),
            DEFAULT_CLOSE_MODE,
            f"{SERVICE_CLOSE_COVER} mode",
        )

        self._unsubs.append(
            self._register_trigger(
                SERVICE_OPEN_COVER,
                open_mode,
                settings.get(CONF_OPEN_TIME),
                int(settings.get(CONF_OPEN_OFFSET, DEFAULT_OPEN_OFFSET)),
            )
        )
        self._unsubs.append(
            self._register_trigger(
                SERVICE_CLOSE_COVER,
                close_mode,
                settings.get(CONF_CLOSE_TIME),
                int(settings.get(CONF_CLOSE_OFFSET, DEFAULT_CLOSE_OFFSET)),
            )
        )

        _LOGGER.debug(
            "Scheduled covers %s: open=(%s) close=(%s)",
            settings.get(CONF_COVERS),
            open_mode,
            close_mode,
        )

    def _resolve_mode(
        self, mode: str, default_mode: str, context: str
    ) -> str:
        """Return a known trigger mode, defaulting + warning on unknown values."""
        if mode in TRIGGER_MODES:
            return mode
        _LOGGER.warning(
            "Unknown trigger mode %r for %s on subentry %s; falling back to %r",
            mode,
            context,
            self.subentry_id,
            default_mode,
        )
        return default_mode

    def _register_trigger(
        self,
        service: str,
        mode: str,
        time_value: str | None,
        offset_min: int,
    ) -> Callable[[], None]:
        """Register a single open/close trigger for the given mode."""
        if mode == MODE_NONE:
            return lambda: None
        handler = self._make_handler(service)
        if mode == MODE_FIXED:
            time_obj = _parse_time(time_value)
            return async_track_time_change(
                self.hass,
                handler,
                hour=time_obj.hour,
                minute=time_obj.minute,
                second=time_obj.second,
            )
        offset_td = timedelta(minutes=offset_min)
        if mode == MODE_SUNRISE:
            return async_track_sunrise(self.hass, handler, offset_td)
        if mode == MODE_SUNSET:
            return async_track_sunset(self.hass, handler, offset_td)
        raise ValueError(f"unexpected trigger mode {mode!r}")

    @callback
    def async_unschedule(self) -> None:
        """Cancel pending listeners and any deferred callbacks."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._pending_unsubs:
            unsub()
        self._pending_unsubs.clear()

    def _make_handler(self, service: str):
        @callback
        def _handle(now: datetime | None = None) -> None:
            current = now if now is not None else dt_util.utcnow()
            self.hass.async_create_task(self._async_trigger(service, current))

        return _handle

    async def _async_trigger(self, service: str, now: datetime) -> None:
        """Decide whether to run the service for this trigger."""
        if not self._conditions_met(service, now):
            return

        delay_seconds = self._compute_delay(now)

        if delay_seconds <= 0:
            await self._async_call(service)
            return

        _LOGGER.debug(
            "Delaying %s by %s seconds (randomized)", service, delay_seconds
        )

        unsub_ref: Callable[[], None] | None = None

        @callback
        def _deferred(_fire_at: datetime) -> None:
            if unsub_ref is not None and unsub_ref in self._pending_unsubs:
                self._pending_unsubs.remove(unsub_ref)
            self.hass.async_create_task(self._async_deferred_call(service))

        unsub_ref = async_call_later(self.hass, delay_seconds, _deferred)
        self._pending_unsubs.append(unsub_ref)

    def _compute_delay(self, now: datetime) -> int:
        """Pick a random delay, capped so it stays in the current day."""
        settings = self._settings
        if not settings.get(CONF_RANDOMIZE):
            return 0
        max_minutes = int(
            settings.get(CONF_RANDOM_MAX_MINUTES, DEFAULT_RANDOM_MAX_MINUTES)
        )
        if max_minutes <= 0:
            return 0

        local_now = dt_util.as_local(now)
        end_of_day = (local_now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        seconds_until_midnight = max(
            0, int((end_of_day - local_now).total_seconds()) - 1
        )
        upper = min(max_minutes * 60, seconds_until_midnight)
        if upper <= 0:
            return 0
        return random.randint(0, upper)

    def _conditions_met(self, service: str, now: datetime) -> bool:
        """Check active day, pause and presence conditions."""
        if self.paused:
            _LOGGER.debug("Skipping %s: simulation is paused", service)
            return False
        settings = self._settings
        local_now = dt_util.as_local(now)
        active_days: list[str] = settings.get(CONF_DAYS, DAYS)
        weekday_key = DAYS[local_now.weekday()]
        if weekday_key not in active_days:
            _LOGGER.debug("Skipping %s: %s not in active days", service, weekday_key)
            return False
        if settings.get(CONF_ONLY_WHEN_AWAY) and not self._is_away(settings):
            _LOGGER.debug("Skipping %s: presence detected at home", service)
            return False
        return True

    async def _async_deferred_call(self, service: str) -> None:
        """Re-check conditions before firing a delayed action."""
        if self.hass.data.get(DOMAIN, {}).get(self.subentry_id) is not self:
            return
        if not self._conditions_met(service, dt_util.utcnow()):
            return
        await self._async_call(service)

    async def _async_call(self, service: str) -> None:
        """Invoke the cover service on all configured entities.

        Two modes, gated by the hub-level ``sequential_covers`` toggle:

        * **Parallel** (default): one batched ``cover.<service>`` call on
          the whole list; HA dispatches immediately, no waiting.
        * **Sequential**: shuffle the list, then for each cover issue
          its own ``blocking=True`` call and wait for the cover state
          to reach the action's target (``open`` / ``closed``) before
          moving on. A per-cover timeout
          (``COVER_ACTION_TIMEOUT_SECONDS``) prevents a stuck or
          stateless cover from blocking the queue indefinitely.

        In both modes, notifications fire **once** at the end (one
        message for the whole batch, not one per cover).
        """
        covers = self._settings.get(CONF_COVERS, [])
        if not covers:
            return

        sequential = self.hub_entry.data.get(
            CONF_SEQUENTIAL_COVERS, DEFAULT_SEQUENTIAL_COVERS
        )

        if sequential:
            processed = list(covers)
            random.shuffle(processed)
            _LOGGER.debug(
                "Sequential cover.%s on %s (random order)", service, processed
            )
            await self._async_call_sequential(service, processed)
        else:
            processed = list(covers)
            await self.hass.services.async_call(
                "cover",
                service,
                {ATTR_ENTITY_ID: processed},
                blocking=False,
            )
            _LOGGER.info("Called cover.%s on %s", service, processed)

        # If we got unloaded mid-call (sequential mode aborts on
        # subentry remove / HA shutdown), don't notify or signal: the
        # subentry is being torn down and the notification would list
        # covers that may not all have been actioned anyway.
        if self.hass.data.get(DOMAIN, {}).get(self.subentry_id) is not self:
            return

        await self._async_send_notifications(service, processed)
        async_dispatcher_send(self.hass, signal_state_update(self.subentry_id))

    async def _async_call_sequential(
        self, service: str, ordered: list[str]
    ) -> None:
        """Run ``cover.<service>`` on each cover in the given order, in turn.

        ``ordered`` is the already-shuffled list; the caller owns the
        shuffling so it can pass the same list down to the notification
        hook (so the body lists covers in processing order).
        """
        target_state = (
            STATE_OPEN if service == SERVICE_OPEN_COVER else STATE_CLOSED
        )
        for entity_id in ordered:
            # If the scheduler was unloaded mid-sequence (entry remove,
            # HA shutdown, ...), bail out cleanly.
            if self.hass.data.get(DOMAIN, {}).get(self.subentry_id) is not self:
                _LOGGER.debug(
                    "Aborting sequential cover sequence: scheduler unloaded"
                )
                return
            await self.hass.services.async_call(
                "cover",
                service,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
            )
            _LOGGER.info("Called cover.%s on %s", service, entity_id)
            await self._async_wait_for_cover_state(entity_id, target_state)

    async def _async_wait_for_cover_state(
        self, entity_id: str, target_state: str
    ) -> None:
        """Wait until ``entity_id`` reaches ``target_state`` or times out.

        Subscribes to state-change events first, *then* re-reads the
        current state. This ordering closes the (theoretical, on
        cooperative scheduling) race window where the cover could flip
        to its target between the read and the subscribe — anything
        that happens before subscribe still triggers a fresh state
        snapshot here, anything after fires the listener.

        Times out after ``COVER_ACTION_TIMEOUT_SECONDS`` if the cover
        never publishes a final state (some minimalist drivers don't);
        the timeout is logged at warning level and the queue moves on
        to the next cover.
        """
        finished = asyncio.Event()

        @callback
        def _on_state_change(event) -> None:
            new_state = event.data.get("new_state")
            if new_state is not None and new_state.state == target_state:
                finished.set()

        unsub = async_track_state_change_event(
            self.hass, [entity_id], _on_state_change
        )
        try:
            current = self.hass.states.get(entity_id)
            if current is not None and current.state == target_state:
                return
            await asyncio.wait_for(
                finished.wait(), timeout=COVER_ACTION_TIMEOUT_SECONDS
            )
        except TimeoutError:
            _LOGGER.warning(
                "Cover %s did not reach state %s within %s seconds; "
                "continuing with the next cover",
                entity_id,
                target_state,
                COVER_ACTION_TIMEOUT_SECONDS,
            )
        finally:
            unsub()

    async def _async_send_notifications(
        self, cover_service: str, processed_covers: list[str]
    ) -> None:
        """Dispatch the action to push notifiers and to TTS speakers.

        ``processed_covers`` is the list of covers in the order the
        scheduler actually fired them — that's the order the user sees
        in the notification body and hears spoken on the smart speaker.

        Push and TTS are two independent branches:

        * Each is gated by its own ``*_when_away_only`` toggle.
        * Each is wrapped in its own try/except so a failure in one
          channel never silences the other (and never propagates back
          up to break the cover action that already succeeded).

        Settings are read from the hub entry on every call (not cached)
        so the hub options flow takes effect without a reload.
        """
        hub_data = self.hub_entry.data
        is_away = self._is_away(self._settings)
        action = ACTION_OPEN if cover_service == SERVICE_OPEN_COVER else ACTION_CLOSE
        language = self.hass.config.language

        await self._async_send_push_notifications(
            hub_data, action, language, is_away, processed_covers
        )
        await self._async_send_tts_announcements(
            hub_data, action, language, is_away, processed_covers
        )

    async def _async_send_push_notifications(
        self,
        hub_data: Mapping[str, Any],
        action: str,
        language: str,
        is_away: bool,
        processed_covers: list[str],
    ) -> None:
        """Send a push notification through every configured ``notify.*`` service."""
        notify_mode = hub_data.get(CONF_NOTIFY_MODE, DEFAULT_NOTIFY_MODE)
        if notify_mode == MODE_DISABLED:
            return
        if notify_mode == MODE_AWAY_ONLY and not is_away:
            return
        targets: list[str] = list(
            hub_data.get(CONF_NOTIFY_SERVICES, DEFAULT_NOTIFY_SERVICES)
        )
        if not targets:
            return

        title = self.subentry.title
        message = _notify_message(self.hass, language, action, processed_covers)

        for target in targets:
            if "." not in target:
                _LOGGER.warning("Invalid notify target: %s", target)
                continue
            domain, service_name = target.split(".", 1)
            if domain != "notify":
                _LOGGER.warning(
                    "Notify target not in notify domain: %s", target
                )
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    service_name,
                    {"title": title, "message": message},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001 — never break the cover action
                _LOGGER.exception(
                    "Failed to send notification via %s", target
                )

    async def _async_send_tts_announcements(
        self,
        hub_data: Mapping[str, Any],
        action: str,
        language: str,
        is_away: bool,
        processed_covers: list[str],
    ) -> None:
        """Speak the action on every configured ``media_player.*`` via ``tts.speak``."""
        tts_mode = hub_data.get(CONF_TTS_MODE, DEFAULT_TTS_MODE)
        if tts_mode == MODE_DISABLED:
            return
        if tts_mode == MODE_AWAY_ONLY and not is_away:
            return
        engine = hub_data.get(CONF_TTS_ENGINE)
        targets: list[str] = list(
            hub_data.get(CONF_TTS_TARGETS, DEFAULT_TTS_TARGETS)
        )
        if not engine or not targets:
            return

        message = _tts_message(self.hass, language, action, processed_covers)
        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": engine,
                    "media_player_entity_id": targets,
                    "message": message,
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001 — never break the cover action
            _LOGGER.exception(
                "Failed to broadcast TTS announcement via %s", engine
            )

    def _is_away(self, settings: dict[str, Any]) -> bool:
        """Return True when the configured presence entity reports away."""
        entity_id = settings.get(CONF_PRESENCE_ENTITY)
        if not entity_id:
            return self._all_persons_away()

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Presence entity %s is unavailable", entity_id)
            return False
        return state.state in AWAY_STATES

    def _all_persons_away(self) -> bool:
        """Fallback presence check across all person entities."""
        persons = self.hass.states.async_all("person")
        if not persons:
            _LOGGER.warning(
                "only_when_away is enabled but no presence entity is "
                "configured and no person.* exists; assuming away so the "
                "simulation can run"
            )
            return True
        return all(p.state in AWAY_STATES for p in persons)

    def next_open(self) -> datetime | None:
        """Return the next scheduled opening as a UTC datetime."""
        return self._next_for(
            CONF_OPEN_TIME, CONF_OPEN_MODE, CONF_OPEN_OFFSET, DEFAULT_OPEN_MODE
        )

    def next_close(self) -> datetime | None:
        """Return the next scheduled closing as a UTC datetime."""
        return self._next_for(
            CONF_CLOSE_TIME, CONF_CLOSE_MODE, CONF_CLOSE_OFFSET, DEFAULT_CLOSE_MODE
        )

    def _next_for(
        self,
        time_key: str,
        mode_key: str,
        offset_key: str,
        default_mode: str,
    ) -> datetime | None:
        """Compute the next trigger, dispatching on the configured mode."""
        if self.paused:
            return None
        settings = self._settings
        days_keys: list[str] = settings.get(CONF_DAYS, DAYS)
        if not days_keys:
            return None
        mode = self._resolve_mode(
            settings.get(mode_key, default_mode), default_mode, mode_key
        )
        if mode == MODE_NONE:
            return None
        if mode == MODE_FIXED:
            time_value = _parse_time(settings[time_key])
            local_now = dt_util.as_local(dt_util.utcnow())
            local_next = _next_datetime_for(local_now, time_value, days_keys)
            if local_next is None:
                return None
            return dt_util.as_utc(local_next)
        if mode == MODE_SUNRISE:
            event = SUN_EVENT_SUNRISE
        elif mode == MODE_SUNSET:
            event = SUN_EVENT_SUNSET
        else:  # pragma: no cover — _resolve_mode already enforces TRIGGER_MODES
            return None
        offset_min = int(settings.get(offset_key, 0))
        return self._next_sun(event, offset_min, days_keys)

    def _next_sun(
        self, event: str, offset_min: int, days_keys: list[str]
    ) -> datetime | None:
        """Find the next sunrise/sunset (with offset) on an active day."""
        offset_td = timedelta(minutes=offset_min)
        candidate = get_astral_event_next(
            self.hass, event, dt_util.utcnow(), offset_td
        )
        for _ in range(8):
            if candidate is None:
                return None
            local = dt_util.as_local(candidate)
            if DAYS[local.weekday()] in days_keys:
                return candidate
            candidate = get_astral_event_next(
                self.hass,
                event,
                candidate + timedelta(seconds=1),
                offset_td,
            )
        return None

    async def async_run_now(self, action: str) -> None:
        """Trigger an immediate open or close, bypassing all conditions."""
        service = SERVICE_OPEN_COVER if action == ACTION_OPEN else SERVICE_CLOSE_COVER
        _LOGGER.info("Manual run_now: %s", service)
        await self._async_call(service)

    async def async_set_paused(self, paused: bool) -> None:
        """Update the paused flag and notify listeners."""
        if self.paused == paused:
            return
        self.paused = paused
        _LOGGER.info("Simulation %s", "paused" if paused else "resumed")
        async_dispatcher_send(self.hass, signal_state_update(self.subentry_id))
