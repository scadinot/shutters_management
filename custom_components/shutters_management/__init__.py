"""Shutters Management integration."""
from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    CONF_NAME,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .panel import async_register_panel, async_unregister_panel
from .scheduler import ShuttersScheduler
from .sun_protection import (
    ShuttersSunProtectionManager,
    _async_restore_cover_positions,
    _restored_positions,
)
from .state_store import ShuttersStateStore
from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    ATTR_ACTION,
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_WHEN_AWAY_ONLY,
    CONF_ONLY_WHEN_AWAY,
    CONF_PRESENCE_ENTITY,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_TTS_ENGINE,
    CONF_TTS_MODE,
    CONF_TTS_TARGETS,
    CONF_TTS_WHEN_AWAY_ONLY,
    CONF_TYPE,
    DEFAULT_NOTIFY_MODE,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_TTS_MODE,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    MODE_ALWAYS,
    MODE_AWAY_ONLY,
    MODE_DISABLED,
    PLATFORMS,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_RUN_NOW,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    TYPE_HUB,
)

_LOGGER = logging.getLogger(__name__)

# Stale `DeviceInfo.model` values defined in v0.4.8/v0.4.9 and removed in v0.4.10.
# Persisted in the device registry until explicitly cleared (HA does not clean
# up fields removed from DeviceInfo). Used by the one-time migration in
# `async_setup_entry`.
_RESIDUAL_DEVICE_MODELS = frozenset({"Presence schedule", "Sun protection"})

# Kept outside ``hass.data[DOMAIN]``, which only holds per-subentry
# managers, and survives reloads of the hub entry.
_STATE_STORE_KEY = f"{DOMAIN}_state_store"


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RUN_NOW_SCHEMA = vol.Schema(
    {vol.Required(ATTR_ACTION): vol.In([ACTION_OPEN, ACTION_CLOSE])}
)


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

    state_store: ShuttersStateStore | None = hass.data.get(_STATE_STORE_KEY)
    if state_store is None:
        state_store = ShuttersStateStore(hass)
        await state_store.async_load()
        hass.data[_STATE_STORE_KEY] = state_store
    state_store.async_prune(entry.subentries)

    for subentry in entry.subentries.values():
        if subentry.subentry_type in (SUBENTRY_TYPE_INSTANCE, SUBENTRY_TYPE_PRESENCE_SIM):
            scheduler = ShuttersScheduler(hass, entry, subentry, state_store)
            scheduler.async_schedule()
            hass.data[DOMAIN][subentry.subentry_id] = scheduler
        elif subentry.subentry_type == SUBENTRY_TYPE_SUN_PROTECTION:
            manager = ShuttersSunProtectionManager(
                hass, entry, subentry, state_store
            )
            await manager.async_setup()
            hass.data[DOMAIN][subentry.subentry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    await _async_register_frontend_resources(hass)
    async_register_panel(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a hub entry and tear down all of its subentry managers.

    Managers are looked up in ``hass.data`` rather than through
    ``entry.subentries``: when a subentry is deleted, the reload that
    follows already sees it gone, and its manager would otherwise stay
    subscribed (and keep driving covers) until the next restart.

    A sun-protection group in sun mode keeps its covers lowered across a
    plain reload (e.g. reconfiguring another subentry): its state is
    persisted and picked up by the manager created on setup. Covers are
    only restored when the group itself goes away: subentry deleted or
    hub disabled. Hub removal is handled by ``async_remove_entry``.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN, {})
    owned = [
        subentry_id
        for subentry_id, manager in domain_data.items()
        if manager.hub_entry is entry
    ]
    for subentry_id in owned:
        manager = domain_data.pop(subentry_id)
        if isinstance(manager, ShuttersScheduler):
            manager.async_unschedule()
        elif isinstance(manager, ShuttersSunProtectionManager):
            await manager.async_unload(
                restore_covers=(
                    subentry_id not in entry.subentries
                    or entry.disabled_by is not None
                )
            )

    async_unregister_panel(hass)

    if not hass.data.get(DOMAIN):
        _async_unregister_services(hass)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Restore lowered covers and delete the persisted state with the hub.

    Unloading keeps a sun mode persisted (see ``async_unload_entry``):
    with the hub gone nothing would ever raise those covers again, so
    they are restored here from the saved snapshots.

    Legacy (pre-hub) entries deleted by the v2→v3 migration never owned
    the store, so they must not wipe it.
    """
    if entry.data.get(CONF_TYPE) != TYPE_HUB:
        return
    state_store: ShuttersStateStore | None = hass.data.pop(
        _STATE_STORE_KEY, None
    )
    if state_store is None:
        state_store = ShuttersStateStore(hass)
        await state_store.async_load()
    for saved in state_store.all().values():
        if saved.get("in_sun_mode"):
            await _async_restore_cover_positions(
                hass,
                _restored_positions(saved.get("snapshots")),
                _restored_positions(saved.get("applied_positions")),
            )
    await state_store.async_remove()


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
        # Hub-only change (e.g. presence_entity edited from the options
        # flow): no scheduler / manager respawn needed, but the panel
        # references the hub data and must be rebuilt to reflect it.
        async_register_panel(hass, entry)
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


_FRONTEND_DIR = "frontend"
_FRONTEND_URL = f"/{DOMAIN}_frontend"
_CARD_URL = f"{_FRONTEND_URL}/shutters-sun-3d-card.js"
_FRONTEND_REGISTERED_FLAG = f"{DOMAIN}_frontend_registered"


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve the custom Lovelace card and register it as a frontend module.

    Idempotent across reloads of the integration: a flag in
    ``hass.data`` guards a second registration attempt. Removing
    static paths or extra JS modules requires a HA restart, which is
    acceptable for a ``single_config_entry`` integration.

    Defensive against test harnesses where the ``frontend`` component
    is not fully set up: ``DATA_EXTRA_MODULE_URL`` is initialized via
    ``setdefault`` so ``add_extra_js_url`` does not KeyError.
    """
    if hass.data.get(_FRONTEND_REGISTERED_FLAG):
        return
    from pathlib import Path

    from homeassistant.components.frontend import (
        DATA_EXTRA_MODULE_URL,
        add_extra_js_url,
    )
    from homeassistant.components.http import StaticPathConfig

    frontend_path = Path(__file__).parent / _FRONTEND_DIR
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_FRONTEND_URL, str(frontend_path), False)]
    )
    hass.data.setdefault(DATA_EXTRA_MODULE_URL, set())
    add_extra_js_url(hass, _CARD_URL)
    hass.data[_FRONTEND_REGISTERED_FLAG] = True


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        return

    def _schedulers() -> list[ShuttersScheduler]:
        return [
            m
            for m in hass.data.get(DOMAIN, {}).values()
            if isinstance(m, ShuttersScheduler)
        ]

    async def _handle_run_now(call: ServiceCall) -> None:
        action = call.data[ATTR_ACTION]
        for scheduler in _schedulers():
            await scheduler.async_run_now(action)

    async def _handle_pause(call: ServiceCall) -> None:
        for scheduler in _schedulers():
            await scheduler.async_set_paused(True)

    async def _handle_resume(call: ServiceCall) -> None:
        for scheduler in _schedulers():
            await scheduler.async_set_paused(False)

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
