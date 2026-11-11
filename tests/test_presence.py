"""Tests for the household-presence helper.

Both branches covered here were unreachable from the rest of the suite before
the `__init__.py` split: a `presence_entity` still stored as a bare string
(the pre-v0.8 shape, normalized to a list by the v7 → v8 migration), and the
`person.*` fallback taken when every configured presence entity is unavailable.
"""
from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from custom_components.shutters_management.const import CONF_PRESENCE_ENTITY
from custom_components.shutters_management.presence import _is_away_for


async def test_is_away_for_accepts_a_bare_string(hass: HomeAssistant) -> None:
    """A presence_entity stored as a string, not a list, is still read."""
    hass.states.async_set("person.alice", "not_home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: "person.alice"}) is True

    hass.states.async_set("person.alice", "home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: "person.alice"}) is False


async def test_is_away_for_falls_back_to_person_scan(hass: HomeAssistant) -> None:
    """Every configured entity unavailable → fall back to scanning person.*."""
    hass.states.async_set("group.presence", STATE_UNAVAILABLE)

    hass.states.async_set("person.alice", "home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: ["group.presence"]}) is False

    hass.states.async_set("person.alice", "not_home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: ["group.presence"]}) is True


async def test_is_away_for_assumes_away_when_the_only_source_is_unknown(
    hass: HomeAssistant,
) -> None:
    """A configured person.* stuck at 'unknown' must not read as 'someone home'.

    The configured entity is skipped as unusable, then the fallback re-scans
    ``person.*`` and gets that very same entity back. ``unknown`` is not in
    ``AWAY_STATES``, so ``all()`` answered False — 'home' — and a schedule
    with ``only_when_away`` stayed put for the whole day. With no usable
    source left, the documented default applies: assume away.
    """
    hass.states.async_set("person.alice", STATE_UNKNOWN)
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: ["person.alice"]}) is True


async def test_is_away_for_assumes_away_when_every_person_is_unavailable(
    hass: HomeAssistant,
) -> None:
    """Nothing configured and every ``person.*`` unavailable → assume away.

    The docstring's promise ("no presence entity configured and no person.*
    exists; assuming away") must hold just as well when the entities exist
    but none of them carries a usable state.
    """
    hass.states.async_set("person.alice", STATE_UNAVAILABLE)
    assert _is_away_for(hass, {}) is True
