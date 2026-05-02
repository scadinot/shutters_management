"""Tests for the v0.4.6 sun-protection orientation groups."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import SERVICE_SET_COVER_POSITION
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.shutters_management.const import (
    CONF_ARC,
    CONF_COVERS,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_ORIENTATION,
    CONF_TARGET_POSITION,
    CONF_TYPE,
    CONF_UV_ENTITY,
    DEFAULT_ARC,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    DEFAULT_TARGET_POSITION,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    SUBENTRY_TYPE_SUN_PROTECTION,
    TYPE_HUB,
)


def _build_hub_with_sun_protection(
    *,
    covers: list[str],
    orientation: int = 180,
    arc: int = DEFAULT_ARC,
    min_elevation: int = DEFAULT_MIN_ELEVATION,
    min_uv: int = DEFAULT_MIN_UV,
    target_position: int = DEFAULT_TARGET_POSITION,
    uv_entity: str = "",
    entry_id: str = "test_hub",
    group_title: str = "Salon Sud",
    group_unique_id: str = "salon_sud",
) -> MockConfigEntry:
    """Build a hub MockConfigEntry with a single sun-protection subentry."""
    hub_data: dict[str, Any] = {
        CONF_TYPE: TYPE_HUB,
        "notify_services": [],
        "notify_mode": "always",
    }
    if uv_entity:
        hub_data[CONF_UV_ENTITY] = uv_entity

    group_data: dict[str, Any] = {
        CONF_COVERS: covers,
        CONF_ORIENTATION: orientation,
        CONF_ARC: arc,
        CONF_MIN_ELEVATION: min_elevation,
        CONF_MIN_UV: min_uv,
        CONF_TARGET_POSITION: target_position,
    }

    return MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data=hub_data,
        options={},
        entry_id=entry_id,
        unique_id=HUB_UNIQUE_ID,
        version=4,
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_SUN_PROTECTION,
                title=group_title,
                unique_id=group_unique_id,
                data=MappingProxyType(group_data),
            )
        ],
    )


def _set_sun(hass: HomeAssistant, *, azimuth: float, elevation: float) -> None:
    hass.states.async_set(
        "sun.sun",
        "above_horizon" if elevation > 0 else "below_horizon",
        {"azimuth": azimuth, "elevation": elevation},
    )


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry
) -> str:
    """Add entry to hass, set up, return subentry_id."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    subentry_ids = list(entry.subentries.keys())
    assert len(subentry_ids) == 1
    return subentry_ids[0]


# ---------------------------------------------------------------------------
# Entering sun mode
# ---------------------------------------------------------------------------


async def test_enters_sun_mode_when_conditions_met(hass: HomeAssistant) -> None:
    """Sun in arc + above elevation → covers lowered to target position."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set(
        "cover.living_room", "open", {"current_position": 100}
    )
    _set_sun(hass, azimuth=180, elevation=30)  # due south, high

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        arc=60,
        min_elevation=15,
        target_position=50,
    )
    await _setup(hass, entry)
    await hass.async_block_till_done()

    assert len(cover_calls) == 1
    assert cover_calls[0].data["entity_id"] == "cover.living_room"
    assert cover_calls[0].data["position"] == 50


async def test_no_activation_when_azimuth_outside_arc(hass: HomeAssistant) -> None:
    """Sun outside the arc → no cover call."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=0, elevation=30)  # north — opposite of south

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        arc=60,
        min_elevation=15,
    )
    await _setup(hass, entry)
    await hass.async_block_till_done()

    assert cover_calls == []


async def test_no_activation_below_elevation(hass: HomeAssistant) -> None:
    """Sun too low → no cover call."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=5)  # in arc but too low

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        arc=60,
        min_elevation=15,
    )
    await _setup(hass, entry)
    await hass.async_block_till_done()

    assert cover_calls == []


# ---------------------------------------------------------------------------
# Restoration on exit
# ---------------------------------------------------------------------------


async def test_exits_sun_mode_and_restores_position(hass: HomeAssistant) -> None:
    """When sun leaves arc, covers return to their snapshot position."""
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 80})
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"], orientation=180, arc=60, min_elevation=15
    )
    subentry_id = await _setup(hass, entry)
    await hass.async_block_till_done()

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_active

    # Sun moves away from arc.
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=0, elevation=30)
    await manager.async_evaluate()
    await hass.async_block_till_done()

    assert not manager.is_active
    # The last call should restore to 80 %.
    restore_call = next(
        (c for c in cover_calls if c.data.get("position") == 80), None
    )
    assert restore_call is not None


async def test_no_restore_when_manually_moved(hass: HomeAssistant) -> None:
    """If cover was moved manually while in sun mode, skip restoration."""
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 80})
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        arc=60,
        min_elevation=15,
        target_position=50,
    )
    subentry_id = await _setup(hass, entry)
    await hass.async_block_till_done()

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_active

    # Simulate manual move to 70 % (different from the 50 % we applied).
    hass.states.async_set("cover.living_room", "open", {"current_position": 70})
    manager._applied_positions["cover.living_room"] = 50  # what we set

    # Sun leaves arc.
    restore_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=0, elevation=30)
    await manager.async_evaluate()
    await hass.async_block_till_done()

    # current_pos (70) ≠ applied (50) → no restore call.
    assert all(c.data.get("position") != 80 for c in restore_calls)


# ---------------------------------------------------------------------------
# UV gating
# ---------------------------------------------------------------------------


async def test_uv_too_low_skips_activation(hass: HomeAssistant) -> None:
    """UV below threshold → no activation even when sun is in arc."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("sensor.uv", "1", {})
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        min_elevation=15,
        min_uv=3,
        uv_entity="sensor.uv",
    )
    await _setup(hass, entry)
    await hass.async_block_till_done()

    assert cover_calls == []


async def test_uv_sufficient_activates(hass: HomeAssistant) -> None:
    """UV at threshold → activation fires."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    hass.states.async_set("sensor.uv", "5", {})
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        min_elevation=15,
        min_uv=3,
        uv_entity="sensor.uv",
    )
    await _setup(hass, entry)
    await hass.async_block_till_done()

    assert len(cover_calls) == 1


# ---------------------------------------------------------------------------
# Switch control
# ---------------------------------------------------------------------------


async def test_switch_disabled_prevents_activation(hass: HomeAssistant) -> None:
    """Disabling the switch before setup → no activation."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"], orientation=180, min_elevation=15
    )
    subentry_id = await _setup(hass, entry)
    await hass.async_block_till_done()

    manager = hass.data[DOMAIN][subentry_id]

    # Disable, then re-evaluate with sun in arc.
    cover_calls.clear()
    manager.set_enabled(False)
    await hass.async_block_till_done()

    assert not manager.is_active


async def test_switch_disabled_exits_sun_mode(hass: HomeAssistant) -> None:
    """Disabling the switch while in sun mode triggers exit (restore)."""
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 80})
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        min_elevation=15,
        target_position=50,
    )
    subentry_id = await _setup(hass, entry)
    await hass.async_block_till_done()

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_active

    restore_calls = async_mock_service(hass, "cover", "set_cover_position")
    manager.set_enabled(False)
    await hass.async_block_till_done()

    assert not manager.is_active
    assert any(c.data.get("position") == 80 for c in restore_calls)


# ---------------------------------------------------------------------------
# Snapshot update on external cover move
# ---------------------------------------------------------------------------


async def test_scheduler_updates_snapshot_on_external_move(
    hass: HomeAssistant,
) -> None:
    """If a cover is moved while in sun mode, snapshot updates to new pos."""
    from homeassistant.core import Event

    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        min_elevation=15,
        target_position=50,
    )
    subentry_id = await _setup(hass, entry)
    await hass.async_block_till_done()

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_active

    # Simulate the cover being moved externally to 30 %.
    hass.states.async_set("cover.living_room", "open", {"current_position": 30})
    new_state = hass.states.get("cover.living_room")

    class FakeEvent:
        data = {
            "entity_id": "cover.living_room",
            "new_state": new_state,
        }

    await manager._async_on_cover_state_change(FakeEvent())

    # Snapshot should now point to 30 (the scheduler took over).
    assert manager._snapshots.get("cover.living_room") == 30
    assert manager._applied_positions.get("cover.living_room") == 30
