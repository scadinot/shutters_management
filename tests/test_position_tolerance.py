"""Tests for the cover position tolerance in sun protection (v0.9.26).

Covers sent to the target position often stop a point or two away
(49 % instead of 50 %). Before v0.9.26 the strict comparison treated
them as manually moved: never restored on sun-mode exit, and later
real manual moves went undetected.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.shutters_management import _async_restore_cover_positions
from custom_components.shutters_management.const import (
    DOMAIN,
    POSITION_TOLERANCE_PCT,
)

from .test_state_persistence import COVER
from .test_sun_mode_reload import _setup_in_sun_mode
from .test_sun_protection import _set_sun

# ``_sun_mode_state``: snapshot 100 %, applied target 50 %.
APPLIED = 50


async def _report_position(hass: HomeAssistant, position: int) -> None:
    hass.states.async_set(COVER, "open", {"current_position": position})
    await hass.async_block_till_done()


async def test_exit_restores_cover_settled_within_tolerance(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _, subentry_id = await _setup_in_sun_mode(hass, hass_storage)
    manager = hass.data[DOMAIN][subentry_id]

    await _report_position(hass, APPLIED - 1)  # stopped at 49 %
    assert manager.is_active
    assert manager.override_until is None

    _set_sun(hass, azimuth=180, elevation=-5)  # sun gone → exit sun mode
    await hass.async_block_till_done()

    assert not manager.is_active
    assert len(cover_calls) == 1
    assert cover_calls[0].data == {"entity_id": COVER, "position": 100}


async def test_jitter_within_tolerance_is_not_a_manual_move(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _, subentry_id = await _setup_in_sun_mode(hass, hass_storage)
    manager = hass.data[DOMAIN][subentry_id]

    await _report_position(hass, APPLIED - 1)
    await _report_position(hass, APPLIED + 1)

    assert manager.is_active
    assert manager.override_until is None


async def test_move_after_settling_near_target_arms_override(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Settled at 49 % then moved to 70 % (inside the transit range):
    only the tolerant settled-at-target check can recognise it."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _, subentry_id = await _setup_in_sun_mode(hass, hass_storage)
    manager = hass.data[DOMAIN][subentry_id]

    await _report_position(hass, APPLIED - 1)
    assert manager.is_active

    await _report_position(hass, 70)

    assert not manager.is_active
    assert manager.override_until is not None
    assert cover_calls == []


async def test_restore_helper_applies_tolerance_boundary(
    hass: HomeAssistant,
) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")

    hass.states.async_set(
        COVER, "open", {"current_position": APPLIED + POSITION_TOLERANCE_PCT}
    )
    restored = await _async_restore_cover_positions(
        hass, {COVER: 100}, {COVER: APPLIED}
    )
    assert restored == [COVER]

    hass.states.async_set(
        COVER, "open", {"current_position": APPLIED + POSITION_TOLERANCE_PCT + 1}
    )
    restored = await _async_restore_cover_positions(
        hass, {COVER: 100}, {COVER: APPLIED}
    )
    assert restored == []

    await hass.async_block_till_done()
    assert len(cover_calls) == 1
