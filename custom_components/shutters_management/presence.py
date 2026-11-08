"""Présence du foyer : décide si la maison doit être considérée vide.

Extrait d'``__init__.py`` sans modification. Utilisé par ``notifications.py``
(pour choisir entre notification et annonce vocale) et par ``scheduler.py``
(pour le mode « seulement quand absent »).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .const import AWAY_STATES, CONF_PRESENCE_ENTITY

_LOGGER = logging.getLogger(__name__)


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
