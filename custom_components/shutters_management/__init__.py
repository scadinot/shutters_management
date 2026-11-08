"""Shutters Management integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .migrations import _async_migrate_legacy_entries, async_migrate_entry
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
    CONF_TYPE,
    DOMAIN,
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

# Surface publique du paquet. ``async_migrate_entry`` doit y figurer : Home
# Assistant la cherche sur le module de l'intégration. Les trois autres sont
# importés depuis le paquet par cinq fichiers de tests, qui restent inchangés.
__all__ = [
    "ShuttersScheduler",
    "ShuttersSunProtectionManager",
    "_async_restore_cover_positions",
    "async_migrate_entry",
]


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
