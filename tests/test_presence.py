"""Tests for the household-presence helper.

Both branches covered here were unreachable from the rest of the suite before
the `__init__.py` split: a `presence_entity` still stored as a bare string
(the pre-v0.8 shape, normalized to a list by the v7 → v8 migration), and the
`person.*` fallback taken when every configured presence entity is unavailable.
"""
from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE
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
