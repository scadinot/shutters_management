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
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
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
    MODE_HOME_ONLY,
    MODE_NONE,
    MODE_SUNRISE,
    MODE_SUNSET,
    PLATFORMS,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_RUN_NOW,
    ARC_HYSTERESIS_DEG,
    CONF_ARC,
    CONF_LUX_ENTITY,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    DEFAULT_MIN_UV,
    CONF_ORIENTATION,
    CONF_TARGET_POSITION,
    CONF_TEMP_INDOOR_ENTITY,
    CONF_TEMP_OUTDOOR_ENTITY,
    CONF_UV_ENTITY,
    DEFAULT_ARC,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_TARGET_POSITION,
    ELEVATION_HYSTERESIS_DEG,
    LUX_CLOSE_DEBOUNCE_SEC,
    LUX_HEATWAVE,
    LUX_MILD,
    LUX_OPEN_DEBOUNCE_SEC,
    LUX_REOPEN,
    LUX_STANDARD,
    OVERRIDE_RESET_HOUR,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    SUN_ENTITY,
    T_INDOOR_MILD_MIN,
    T_INDOOR_REOPEN,
    T_INDOOR_STANDARD_MIN,
    T_OUTDOOR_HEATWAVE,
    T_OUTDOOR_NO_PROTECT,
    T_OUTDOOR_REOPEN,
    T_OUTDOOR_STANDARD,
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


def _is_away_for(hass: HomeAssistant, hub_data: Mapping[str, Any]) -> bool:
    """Return True when every configured presence entity reports away.

    The hub stores ``presence_entity`` as a list of person/group entity
    ids since v0.7.1. We treat the household as away when every listed
    entity reports an away state. Entities whose state is unavailable
    are skipped (logged at warning); if every configured entity is
    unavailable we fall back to scanning ``person.*``. With no
    configured list and no ``person.*`` entities the function assumes
    away — the safest default for callers like the presence simulation
    where running is preferred to skipping.
    """
    raw = hub_data.get(CONF_PRESENCE_ENTITY) or []
    entity_ids = [raw] if isinstance(raw, str) else list(raw)
    entity_ids = [e for e in entity_ids if e]
    if entity_ids:
        usable_states = []
        for entity_id in entity_ids:
            state = hass.states.get(entity_id)
            if state is None or state.state in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                _LOGGER.warning(
                    "Presence entity %s is unavailable", entity_id
                )
                continue
            usable_states.append(state)
        if usable_states:
            return all(s.state in AWAY_STATES for s in usable_states)
        _LOGGER.warning(
            "All configured presence entities are unavailable; "
            "falling back to person.* scan"
        )
    persons = hass.states.async_all("person")
    if not persons:
        _LOGGER.warning(
            "Presence-aware mode requested but no presence entity is "
            "configured and no person.* exists; assuming away"
        )
        return True
    return all(p.state in AWAY_STATES for p in persons)


async def _async_dispatch_notifications(
    hass: HomeAssistant,
    hub_entry: ConfigEntry,
    subentry: ConfigSubentry,
    action: str,
    processed_covers: list[str],
) -> None:
    """Dispatch a cover action to push + TTS channels.

    Channels (notify services, TTS engine, speakers) and the presence
    entity live on the hub. Each subentry carries its own ``notify_mode``
    and ``tts_mode``: callers don't need to gate themselves — this
    helper consults both modes and short-circuits when the relevant
    channel is disabled or out of scope (e.g. ``home_only`` while away).

    Push and TTS are independent branches; a failure in one never
    silences the other.
    """
    hub_data = hub_entry.data
    sub_data = subentry.data
    is_away = _is_away_for(hass, hub_data)
    language = hass.config.language

    await _async_send_push(
        hass, hub_data, sub_data, subentry, action, language, is_away,
        processed_covers,
    )
    await _async_send_tts(
        hass, hub_data, sub_data, action, language, is_away,
        processed_covers,
    )


async def _async_send_push(
    hass: HomeAssistant,
    hub_data: Mapping[str, Any],
    sub_data: Mapping[str, Any],
    subentry: ConfigSubentry,
    action: str,
    language: str,
    is_away: bool,
    processed_covers: list[str],
) -> None:
    """Send a push notification through every configured ``notify.*`` service."""
    notify_mode = sub_data.get(CONF_NOTIFY_MODE, DEFAULT_NOTIFY_MODE)
    if notify_mode == MODE_DISABLED:
        return
    if notify_mode == MODE_AWAY_ONLY and not is_away:
        return
    targets: list[str] = list(
        hub_data.get(CONF_NOTIFY_SERVICES, DEFAULT_NOTIFY_SERVICES)
    )
    if not targets:
        return

    title = subentry.title
    message = _notify_message(hass, language, action, processed_covers)

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
            await hass.services.async_call(
                "notify",
                service_name,
                {"title": title, "message": message},
                blocking=False,
            )
        except Exception:  # noqa: BLE001 — never break the cover action
            _LOGGER.exception(
                "Failed to send notification via %s", target
            )


async def _async_send_tts(
    hass: HomeAssistant,
    hub_data: Mapping[str, Any],
    sub_data: Mapping[str, Any],
    action: str,
    language: str,
    is_away: bool,
    processed_covers: list[str],
) -> None:
    """Speak the action on every configured ``media_player.*`` via ``tts.speak``."""
    tts_mode = sub_data.get(CONF_TTS_MODE, DEFAULT_TTS_MODE)
    if tts_mode == MODE_DISABLED:
        return
    if tts_mode == MODE_HOME_ONLY and is_away:
        return
    engine = hub_data.get(CONF_TTS_ENGINE)
    targets: list[str] = list(
        hub_data.get(CONF_TTS_TARGETS, DEFAULT_TTS_TARGETS)
    )
    if not engine or not targets:
        return

    message = _tts_message(hass, language, action, processed_covers)
    try:
        await hass.services.async_call(
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

    if entry.version < 6:
        # v5 → v6: extends sun protection with lux + adaptive temperature.
        # Existing ``uv_entity`` (hub) and ``min_uv`` (sun_protection
        # subentry) are preserved — the UV gate remains available as a
        # standalone alternative or in addition to the lux gate. New
        # fields (``lux_entity``, ``temp_outdoor_entity``,
        # ``temp_indoor_entity``) stay absent until the user configures
        # them via the options / reconfigure flows. Schema-wise this is
        # purely additive, so the migration is just a version bump.
        hass.config_entries.async_update_entry(entry, version=6)
        _LOGGER.info(
            "Migrated entry %s from version 5 to 6 (sun-protection v2)",
            entry.entry_id,
        )

    if entry.version < 7:
        # v6 → v7: per-subentry notify/TTS modes, presence_entity at hub.
        #
        # The hub-wide ``notify_mode`` / ``tts_mode`` are removed: each
        # subentry now carries its own copy. ``tts_mode=away_only`` has
        # no equivalent in the new UI (replaced by ``home_only``) and is
        # forced to ``disabled`` so the user explicitly opts back in.
        # ``presence_entity`` migrates from the first non-empty
        # presence_simulation subentry up to the hub, where it is shared
        # by every subentry's away/home mode evaluation.
        hub_data = dict(entry.data)
        hub_notify_mode = hub_data.pop(CONF_NOTIFY_MODE, DEFAULT_NOTIFY_MODE)
        hub_tts_mode = hub_data.pop(CONF_TTS_MODE, DEFAULT_TTS_MODE)
        if hub_tts_mode == MODE_AWAY_ONLY:
            hub_tts_mode = MODE_DISABLED

        presence_entity = hub_data.get(CONF_PRESENCE_ENTITY) or ""
        for subentry in entry.subentries.values():
            if presence_entity:
                break
            sub_presence = subentry.data.get(CONF_PRESENCE_ENTITY)
            if sub_presence:
                presence_entity = sub_presence
        hub_data[CONF_PRESENCE_ENTITY] = presence_entity

        for subentry in entry.subentries.values():
            sd = dict(subentry.data)
            sd.setdefault(CONF_NOTIFY_MODE, hub_notify_mode)
            sd.setdefault(CONF_TTS_MODE, hub_tts_mode)
            sd.pop(CONF_PRESENCE_ENTITY, None)
            if sd != dict(subentry.data):
                hass.config_entries.async_update_subentry(
                    entry, subentry, data=sd
                )

        hass.config_entries.async_update_entry(
            entry, data=hub_data, version=7
        )
        _LOGGER.info(
            "Migrated entry %s from version 6 to 7 (per-subentry notify/TTS modes)",
            entry.entry_id,
        )

    if entry.version < 8:
        # v7 → v8: presence_entity becomes a list of entity ids.
        #
        # The hub stored a single ``person`` or ``group`` id since v0.7.0.
        # As of v0.7.1 the selector is multi-valued, so wrap any legacy
        # string into a one-element list (or an empty list when nothing
        # was configured).
        hub_data = dict(entry.data)
        raw = hub_data.get(CONF_PRESENCE_ENTITY)
        if isinstance(raw, str):
            hub_data[CONF_PRESENCE_ENTITY] = [raw] if raw else []
        elif raw is None:
            hub_data[CONF_PRESENCE_ENTITY] = []
        hass.config_entries.async_update_entry(
            entry, data=hub_data, version=8
        )
        _LOGGER.info(
            "Migrated entry %s from version 7 to 8 (presence_entity as list)",
            entry.entry_id,
        )

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
    """Manage sun-position-based shutter lowering for one orientation group.

    Activation logic combines four sources:

    * **Sun position** (azimuth + elevation) — geometric pre-condition.
    * **Outdoor lux** (mandatory hub sensor) — arbiter of "is the sun
      actually shining". Adaptive threshold: tighter when it is hot.
    * **Outdoor temperature** (optional hub sensor) — protects solar gain
      below ``T_OUTDOOR_NO_PROTECT`` (mid-season / winter).
    * **Indoor temperature** (optional per-group sensor) — final comfort
      gate; bypassed in heatwave so we can pre-protect.

    Hysteresis (``ARC_HYSTERESIS_DEG`` / ``LUX_REOPEN`` / ...) and
    debouncing (``LUX_*_DEBOUNCE_SEC``) prevent yo-yo behaviour at the
    boundaries and through passing clouds. Manual moves on a controlled
    cover trigger a per-façade override that pauses the automation
    until the next ``OVERRIDE_RESET_HOUR`` (default 04:00 local time).
    """

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
        self._override_until: datetime | None = None
        self._lux_above_since: datetime | None = None
        self._lux_below_since: datetime | None = None
        self._last_status: str = "disabled"

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
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
        return self._last_status

    @property
    def override_until(self) -> datetime | None:
        return self._override_until

    # ------------------------------------------------------------------
    # Sensor readers (public so binary_sensor / tests can introspect)
    # ------------------------------------------------------------------
    def _read_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", None):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @property
    def lux(self) -> float | None:
        return self._read_float(
            self.hub_entry.data.get(CONF_LUX_ENTITY) or None
        )

    @property
    def temp_outdoor(self) -> float | None:
        return self._read_float(
            self.hub_entry.data.get(CONF_TEMP_OUTDOOR_ENTITY) or None
        )

    @property
    def temp_indoor(self) -> float | None:
        return self._read_float(
            self.subentry.data.get(CONF_TEMP_INDOOR_ENTITY) or None
        )

    @property
    def uv(self) -> float | None:
        return self._read_float(
            self.hub_entry.data.get(CONF_UV_ENTITY) or None
        )

    # ------------------------------------------------------------------
    # Diagnostic readers (no decision impact, surfaced by sensor entities)
    # ------------------------------------------------------------------
    @property
    def azimuth(self) -> float | None:
        """Sun azimuth in degrees, or ``None`` when sun.sun is missing."""
        state = self.hass.states.get(SUN_ENTITY)
        if state is None:
            return None
        raw = state.attributes.get("azimuth")
        try:
            return float(raw) if raw is not None else None
        except (ValueError, TypeError):
            return None

    @property
    def elevation(self) -> float | None:
        """Sun elevation in degrees, or ``None`` when sun.sun is missing."""
        state = self.hass.states.get(SUN_ENTITY)
        if state is None:
            return None
        raw = state.attributes.get("elevation")
        try:
            return float(raw) if raw is not None else None
        except (ValueError, TypeError):
            return None

    @property
    def azimuth_diff(self) -> float | None:
        """Absolute angular distance from configured orientation, or ``None``.

        Positive ``float`` in ``[0, 180]``. Compared against ``CONF_ARC`` to
        decide whether the sun is in front of the façade.
        """
        az = self.azimuth
        if az is None:
            return None
        orientation = self.subentry.data.get(CONF_ORIENTATION, 180)
        return abs((az - orientation + 180) % 360 - 180)

    @property
    def is_sun_facing(self) -> bool:
        """Geometric only: in arc AND above ``min_elevation``.

        Independent of lux / UV / temperature / override / switch — useful
        as a "would I close *if* it were bright enough?" indicator that
        helps users calibrate ``arc`` and ``min_elevation``.
        """
        diff = self.azimuth_diff
        elev = self.elevation
        if diff is None or elev is None:
            return False
        arc = self.subentry.data.get(CONF_ARC, DEFAULT_ARC)
        min_el = self.subentry.data.get(
            CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION
        )
        return diff <= arc and elev >= min_el

    @property
    def lux_close_threshold(self) -> int | None:
        """Effective adaptive lux threshold for the current ``T_ext``.

        ``None`` when no lux gate applies — either because no lux sensor is
        configured at the hub or because outdoor is below
        ``T_OUTDOOR_NO_PROTECT``.
        """
        if not (self.hub_entry.data.get(CONF_LUX_ENTITY) or ""):
            return None
        return self._close_lux_threshold(self.temp_outdoor)

    @property
    def pending_seconds(self) -> int:
        """Remaining seconds in the active debounce, 0 when none.

        Either the close-debounce (lux above threshold, waiting for
        ``LUX_CLOSE_DEBOUNCE_SEC``) or the open-debounce (lux below
        ``LUX_REOPEN``, waiting for ``LUX_OPEN_DEBOUNCE_SEC``) — the two
        cannot be active at the same time so we surface a single value.
        """
        now = dt_util.now()
        if self._lux_above_since is not None:
            elapsed = (now - self._lux_above_since).total_seconds()
            return max(0, int(LUX_CLOSE_DEBOUNCE_SEC - elapsed))
        if self._lux_below_since is not None:
            elapsed = (now - self._lux_below_since).total_seconds()
            return max(0, int(LUX_OPEN_DEBOUNCE_SEC - elapsed))
        return 0

    # ------------------------------------------------------------------
    # Adaptive thresholds (close)
    # ------------------------------------------------------------------
    @staticmethod
    def _close_lux_threshold(t_ext: float | None) -> int | None:
        """Return the lux threshold required to close at this T_ext.

        ``None`` means the outdoor temperature is below
        ``T_OUTDOOR_NO_PROTECT`` and we want to keep solar gain.
        ``T_ext`` itself missing falls back to the standard threshold so
        the feature still works without an outdoor sensor.
        """
        if t_ext is None:
            return LUX_STANDARD
        if t_ext < T_OUTDOOR_NO_PROTECT:
            return None
        if t_ext < T_OUTDOOR_STANDARD:
            return LUX_MILD
        if t_ext < T_OUTDOOR_HEATWAVE:
            return LUX_STANDARD
        return LUX_HEATWAVE

    @staticmethod
    def _close_indoor_min(t_ext: float | None) -> int | None:
        """Indoor temperature required to close at this T_ext.

        ``None`` means the indoor check is bypassed:

        * no outdoor sensor → we don't know the temperature bracket,
          fall back to lux-only gating (no comfort gate).
        * heatwave bracket → pre-protect even with a cool room.
        """
        if t_ext is None:
            return None
        if t_ext < T_OUTDOOR_NO_PROTECT:
            return None
        if t_ext < T_OUTDOOR_STANDARD:
            return T_INDOOR_MILD_MIN
        if t_ext < T_OUTDOOR_HEATWAVE:
            return T_INDOOR_STANDARD_MIN
        return None  # heatwave: ignore indoor temperature

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------
    async def async_setup(self) -> None:
        """Subscribe to sun, lux, temp and cover state changes."""
        watched = [SUN_ENTITY]
        for key, src in (
            (CONF_LUX_ENTITY, self.hub_entry.data),
            (CONF_UV_ENTITY, self.hub_entry.data),
            (CONF_TEMP_OUTDOOR_ENTITY, self.hub_entry.data),
            (CONF_TEMP_INDOOR_ENTITY, self.subentry.data),
        ):
            entity_id = src.get(key) or ""
            if entity_id:
                watched.append(entity_id)
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, watched, self._async_on_state_change
            )
        )
        covers = list(self.subentry.data.get(CONF_COVERS, []))
        if covers:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, covers, self._async_on_cover_state_change
                )
            )
        # Daily reset of the manual override.
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._async_daily_reset,
                hour=OVERRIDE_RESET_HOUR,
                minute=0,
                second=0,
            )
        )
        # Run the initial evaluate inline so callers can rely on the
        # manager's status / decision state being up-to-date right after
        # ``async_setup`` returns. (``async_call_later(0, …)`` was
        # previously used here, but that path is not deterministic under
        # ``freezegun`` in tests.)
        await self.async_evaluate()

    async def async_unload(self) -> None:
        """Cancel subscriptions and restore positions if in sun mode."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._in_sun_mode:
            await self._async_exit_sun_mode()

    async def _async_on_state_change(self, event: Any) -> None:
        await self.async_evaluate()

    async def _async_daily_reset(self, _now: datetime) -> None:
        if self._override_until is not None:
            _LOGGER.debug(
                "Sun protection %s: override expired at daily reset",
                self.subentry_id,
            )
            self._override_until = None
            await self.async_evaluate()

    # ------------------------------------------------------------------
    # Override helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _next_reset_time(now: datetime) -> datetime:
        """Next ``OVERRIDE_RESET_HOUR`` strictly after ``now`` (local TZ)."""
        target = now.replace(
            hour=OVERRIDE_RESET_HOUR, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return target

    def _override_active(self, now: datetime) -> bool:
        return self._override_until is not None and self._override_until > now

    # ------------------------------------------------------------------
    # Decision engine
    # ------------------------------------------------------------------
    async def async_evaluate(self) -> None:
        """Recompute whether sun protection should be active and act."""
        now = dt_util.now()
        new_status, want_close, want_open = self._compute_decision(now)
        self._last_status = new_status

        if want_close and not self._in_sun_mode:
            await self._async_enter_sun_mode()
        elif want_open and self._in_sun_mode:
            await self._async_exit_sun_mode()

        async_dispatcher_send(
            self.hass, signal_state_update(self.subentry_id)
        )

    def _compute_decision(
        self, now: datetime
    ) -> tuple[str, bool, bool]:
        """Pure decision: returns (status, want_close, want_open).

        ``want_close`` and ``want_open`` are mutually exclusive (only one
        — at most — is True). The status string is exposed by the
        binary_sensor and is informational; it does not gate behaviour.
        Every early-return branch clears the debounce timestamps so the
        ``pending_seconds`` diagnostic never advertises a phantom
        countdown when no debounce is in flight.
        """
        if not self._enabled:
            self._lux_above_since = None
            self._lux_below_since = None
            return ("disabled", False, self._in_sun_mode)

        if self._override_active(now):
            self._lux_above_since = None
            self._lux_below_since = None
            return ("override", False, False)

        lux_entity = self.hub_entry.data.get(CONF_LUX_ENTITY) or ""
        uv_entity = self.hub_entry.data.get(CONF_UV_ENTITY) or ""
        if not lux_entity and not uv_entity:
            # Neither light sensor configured: feature is OFF. Combined
            # with the per-group switch this gives users a reliable kill
            # switch — without a brightness signal we cannot tell if it
            # is actually sunny vs. just geometrically aligned.
            self._lux_above_since = None
            self._lux_below_since = None
            return ("no_sensor", False, self._in_sun_mode)

        sun_state = self.hass.states.get(SUN_ENTITY)
        if sun_state is None:
            # HA startup race or sun integration absent. Treat as
            # "no sun": clear debounce timers and request an exit if we
            # were left in sun mode, so the covers don't stay lowered
            # indefinitely.
            self._lux_above_since = None
            self._lux_below_since = None
            return ("below_horizon", False, self._in_sun_mode)

        elevation = float(sun_state.attributes.get("elevation", 0) or 0)
        azimuth = float(sun_state.attributes.get("azimuth", 0) or 0)
        data = self.subentry.data
        min_elevation = data.get(CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION)
        orientation = data.get(CONF_ORIENTATION, 180)
        arc = data.get(CONF_ARC, DEFAULT_ARC)
        diff = abs((azimuth - orientation + 180) % 360 - 180)

        t_ext = self.temp_outdoor
        t_indoor = self.temp_indoor
        lux = self.lux
        uv = self.uv
        min_uv = int(data.get(CONF_MIN_UV, DEFAULT_MIN_UV))

        # ------------------------------------------------------------------
        # Already in sun mode: only the OPEN path applies (with hysteresis).
        # The close-debounce timer is irrelevant here, clear it once.
        # ------------------------------------------------------------------
        if self._in_sun_mode:
            self._lux_above_since = None
            if elevation < min_elevation - ELEVATION_HYSTERESIS_DEG:
                self._lux_below_since = None
                return ("below_horizon", False, True)
            if diff > arc + ARC_HYSTERESIS_DEG:
                self._lux_below_since = None
                return ("out_of_arc", False, True)
            # Lux exit (debounced) — also fires when the configured lux
            # sensor goes unknown/unavailable, so we don't stay stuck
            # closed indefinitely with no way to re-evaluate light.
            if lux_entity:
                if lux is None or lux < LUX_REOPEN:
                    if self._lux_below_since is None:
                        self._lux_below_since = now
                    if (
                        now - self._lux_below_since
                    ).total_seconds() >= LUX_OPEN_DEBOUNCE_SEC:
                        self._lux_below_since = None
                        return ("lux_too_low", False, True)
                else:
                    self._lux_below_since = None
            else:
                # No lux gate at all — the timer must not linger.
                self._lux_below_since = None
            # UV exit — no debounce, UV index changes slowly enough. A
            # missing reading (sensor unknown/unavailable) is treated as
            # a failed gate so we exit rather than freezing closed.
            if uv_entity and (uv is None or uv < min_uv):
                self._lux_below_since = None
                return ("uv_too_low", False, True)
            # Comfort exit: room cool AND outdoor cool together.
            if (
                t_indoor is not None
                and t_indoor < T_INDOOR_REOPEN
                and t_ext is not None
                and t_ext < T_OUTDOOR_REOPEN
            ):
                self._lux_below_since = None
                return ("room_too_cool", False, True)
            return ("active", False, False)

        # ------------------------------------------------------------------
        # Not in sun mode: evaluate the CLOSE path. The open-debounce
        # timer is irrelevant here, clear it once.
        # ------------------------------------------------------------------
        self._lux_below_since = None
        if elevation < min_elevation:
            self._lux_above_since = None
            return ("below_horizon", False, False)
        if diff > arc:
            self._lux_above_since = None
            return ("out_of_arc", False, False)

        # Universal: outdoor too cold → keep the solar gain.
        if t_ext is not None and t_ext < T_OUTDOOR_NO_PROTECT:
            self._lux_above_since = None
            return ("temp_too_cold", False, False)

        # Lux gate (only when configured).
        if lux_entity:
            # ``_close_lux_threshold`` returns ``None`` only for the
            # too-cold branch we already handled above, so we coalesce
            # to the standard threshold defensively.
            close_lux = self._close_lux_threshold(t_ext) or LUX_STANDARD
            if lux is None or lux < close_lux:
                self._lux_above_since = None
                return ("lux_too_low", False, False)

        # UV gate (only when configured).
        if uv_entity and (uv is None or uv < min_uv):
            self._lux_above_since = None
            return ("uv_too_low", False, False)

        # Indoor comfort gate. If the user has wired an indoor sensor
        # and we are in a temperature bracket where it matters, a
        # missing reading must block the close — closing despite an
        # invisible room temperature would defeat the comfort guarantee.
        indoor_min = self._close_indoor_min(t_ext)
        indoor_entity = (
            self.subentry.data.get(CONF_TEMP_INDOOR_ENTITY) or ""
        )
        if indoor_min is not None and indoor_entity:
            if t_indoor is None or t_indoor < indoor_min:
                self._lux_above_since = None
                return ("room_too_cool", False, False)

        # All instantaneous conditions met. Debounce sustained sunshine
        # only when lux is the gating signal — UV moves slowly enough on
        # its own and a UV-only setup should react immediately.
        if lux_entity:
            if self._lux_above_since is None:
                self._lux_above_since = now
            elapsed = (now - self._lux_above_since).total_seconds()
            if elapsed < LUX_CLOSE_DEBOUNCE_SEC:
                return ("pending_close", False, False)

        self._lux_above_since = None
        return ("active", True, False)

    # ------------------------------------------------------------------
    # Cover commands
    # ------------------------------------------------------------------
    async def _async_enter_sun_mode(self) -> None:
        """Snapshot current positions and lower covers to target."""
        covers = list(self.subentry.data.get(CONF_COVERS, []))
        target = self.subentry.data.get(
            CONF_TARGET_POSITION, DEFAULT_TARGET_POSITION
        )

        processed: list[str] = []
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
            processed.append(cover_id)

        self._in_sun_mode = True
        _LOGGER.debug(
            "Sun protection %s: entered sun mode (target=%s%%)",
            self.subentry_id,
            target,
        )

        if processed:
            await _async_dispatch_notifications(
                self.hass,
                self.hub_entry,
                self.subentry,
                ACTION_CLOSE,
                processed,
            )

    async def _async_exit_sun_mode(self) -> None:
        """Restore cover positions, skipping any that were manually moved."""
        covers = list(self.subentry.data.get(CONF_COVERS, []))

        processed: list[str] = []
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
            if current_pos is None or current_pos == applied:
                await self.hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    {"entity_id": cover_id, "position": snapshot},
                )
                processed.append(cover_id)

        self._in_sun_mode = False
        self._snapshots.clear()
        self._applied_positions.clear()
        _LOGGER.debug("Sun protection %s: exited sun mode", self.subentry_id)

        if processed:
            await _async_dispatch_notifications(
                self.hass,
                self.hub_entry,
                self.subentry,
                ACTION_OPEN,
                processed,
            )

    async def _async_on_cover_state_change(self, event: Any) -> None:
        """Detect external cover moves and arm the manual override.

        While the cover is transiting toward the applied target the
        registry replays intermediate positions in the
        ``[snapshot, applied]`` range; these must be ignored. A move is
        "manual" if either:

        * the cover has already **settled at the applied target** (its
          previous state had ``current_position == applied``) and now
          changed — it could only change because the user pressed a
          remote / app button, OR
        * the new position lands **outside the transit range** (the
          cover is e.g. opening past ``snapshot`` or closing past
          ``applied``).

        In either case we arm the per-façade override until the next
        ``OVERRIDE_RESET_HOUR`` and exit sun mode without re-driving the
        covers (the user just expressed a preference).
        """
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

        old_state = event.data.get("old_state")
        old_pos: int | None = None
        if old_state is not None:
            raw_old = old_state.attributes.get("current_position")
            if raw_old is not None:
                old_pos = int(raw_old)

        # Settled-at-target heuristic: if the cover was at the applied
        # target and now isn't, it's a manual change.
        settled_then_moved = (
            applied is not None
            and old_pos is not None
            and old_pos == applied
            and new_pos_int != applied
        )
        out_of_transit = (
            applied is not None
            and snapshot is not None
            and not (min(snapshot, applied) <= new_pos_int <= max(snapshot, applied))
        )

        if not (settled_then_moved or out_of_transit):
            return  # transit position; nothing to do.

        now = dt_util.now()
        self._override_until = self._next_reset_time(now)
        self._in_sun_mode = False
        self._snapshots.clear()
        self._applied_positions.clear()
        self._lux_above_since = None
        self._lux_below_since = None
        self._last_status = "override"
        _LOGGER.debug(
            "Sun protection %s: manual move detected, override until %s",
            self.subentry_id,
            self._override_until.isoformat(),
        )
        async_dispatcher_send(
            self.hass, signal_state_update(self.subentry_id)
        )

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
        if settings.get(CONF_ONLY_WHEN_AWAY) and not _is_away_for(
            self.hass, self.hub_entry.data
        ):
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
        """Dispatch the action to push notifiers and to TTS speakers."""
        action = ACTION_OPEN if cover_service == SERVICE_OPEN_COVER else ACTION_CLOSE
        await _async_dispatch_notifications(
            self.hass,
            self.hub_entry,
            self.subentry,
            action,
            processed_covers,
        )

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
