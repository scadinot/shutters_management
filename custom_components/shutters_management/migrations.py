"""Montée de version des données de configuration (v2 → v8).

Extrait d'``__init__.py`` sans modification. ``async_migrate_entry`` est
appelée par Home Assistant pour chaque entrée dont la version est antérieure à
``ENTRY_VERSION`` ; ``_async_migrate_legacy_entries`` traite le cas particulier
des entrées pré-v0.4.0, qui doivent être repliées en sous-entrées d'un hub
unique avant toute mise en place par entrée.
"""
from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any


from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    CONF_NAME,
)
from homeassistant.core import (
    HomeAssistant,
)

from .const import (
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
    SUBENTRY_TYPE_INSTANCE,
    TYPE_HUB,
)
_LOGGER = logging.getLogger(__name__)


def _strip_name(data: dict[str, Any]) -> dict[str, Any]:
    """Drop CONF_NAME from a payload destined to ``ConfigSubentry.data``."""
    return {k: v for k, v in data.items() if k != CONF_NAME}


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
