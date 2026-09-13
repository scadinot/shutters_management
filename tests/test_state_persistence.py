"""Tests for the runtime state persisted across restarts (v0.9.22).

A "restart" is simulated by seeding the mocked ``.storage`` document
before the hub entry is set up.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.shutters_management.const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)

from .conftest import build_hub_with_instance, get_only_subentry_id
from .test_sun_protection import _build_hub_with_sun_protection, _set_sun

COVER = "cover.living_room"


def _seed_storage(hass_storage: dict[str, Any], data: dict[str, Any]) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": data,
    }


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _flush_storage(hass: HomeAssistant) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=STORAGE_SAVE_DELAY + 1)
    )
    await hass.async_block_till_done()


def _switch_state(hass: HomeAssistant, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, unique_id
    )
    assert entity_id is not None
    return hass.states.get(entity_id).state


def _sun_mode_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "in_sun_mode": True,
        "snapshots": {COVER: 100},
        "applied_positions": {COVER: 50},
        "override_until": None,
    }


# ---------------------------------------------------------------------------
# Schedules / presence simulations
# ---------------------------------------------------------------------------


async def test_paused_schedule_survives_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any], base_config
) -> None:
    """A schedule paused before a restart stays paused afterwards."""
    entry = build_hub_with_instance(instance_data=base_config)
    subentry_id = get_only_subentry_id(entry)
    _seed_storage(hass_storage, {subentry_id: {"paused": True}})

    await _setup(hass, entry)

    assert hass.data[DOMAIN][subentry_id].paused is True
    assert _switch_state(hass, f"{subentry_id}_simulation_active") == "off"


async def test_pause_is_written_to_storage(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_integration,
    mock_config_entry: MockConfigEntry,
) -> None:
    scheduler = setup_integration
    await scheduler.async_set_paused(True)
    await _flush_storage(hass)

    subentry_id = get_only_subentry_id(mock_config_entry)
    assert hass_storage[STORAGE_KEY]["data"][subentry_id] == {"paused": True}


async def test_state_of_removed_subentries_is_pruned(
    hass: HomeAssistant, hass_storage: dict[str, Any], base_config
) -> None:
    entry = build_hub_with_instance(instance_data=base_config)
    subentry_id = get_only_subentry_id(entry)
    _seed_storage(
        hass_storage,
        {"removed_subentry": {"paused": True}, subentry_id: {"paused": False}},
    )

    await _setup(hass, entry)
    await _flush_storage(hass)

    assert hass_storage[STORAGE_KEY]["data"] == {subentry_id: {"paused": False}}


# ---------------------------------------------------------------------------
# Sun protection
# ---------------------------------------------------------------------------


async def test_disabled_sun_protection_survives_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=40)
    entry = _build_hub_with_sun_protection(covers=[COVER])
    subentry_id = get_only_subentry_id(entry)
    _seed_storage(hass_storage, {subentry_id: {"enabled": False}})

    await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_enabled is False
    assert manager.status == "disabled"
    assert _switch_state(hass, f"{subentry_id}_sun_protection") == "off"
    assert cover_calls == []


async def test_restored_sun_mode_restores_snapshot_on_exit(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Positions saved before the restart are the ones restored on exit.

    Without persistence the snapshot was lost: the covers stayed at the
    applied target position after the sun left the façade.
    """
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=-5)  # sun gone → exit sun mode
    entry = _build_hub_with_sun_protection(covers=[COVER])
    subentry_id = get_only_subentry_id(entry)
    _seed_storage(hass_storage, {subentry_id: _sun_mode_state()})

    await _setup(hass, entry)

    assert len(cover_calls) == 1
    assert cover_calls[0].data == {"entity_id": COVER, "position": 100}
    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_active is False

    await _flush_storage(hass)
    saved = hass_storage[STORAGE_KEY]["data"][subentry_id]
    assert saved["in_sun_mode"] is False
    assert saved["snapshots"] == {}


async def test_override_survives_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=40)
    entry = _build_hub_with_sun_protection(covers=[COVER])
    subentry_id = get_only_subentry_id(entry)
    override_until = (dt_util.now() + timedelta(hours=2)).replace(microsecond=0)
    _seed_storage(
        hass_storage,
        {
            subentry_id: {
                "enabled": True,
                "in_sun_mode": False,
                "override_until": override_until.isoformat(),
            }
        },
    )

    await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.override_until == override_until
    assert manager.status == "override"


async def test_sun_protection_waits_for_ha_started(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """At boot, a restored sun mode is only evaluated once HA has started."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=-5)
    entry = _build_hub_with_sun_protection(covers=[COVER])
    subentry_id = get_only_subentry_id(entry)
    _seed_storage(hass_storage, {subentry_id: _sun_mode_state()})

    hass.set_state(CoreState.not_running)
    await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert cover_calls == []
    assert manager.is_active is True

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert len(cover_calls) == 1
    assert cover_calls[0].data == {"entity_id": COVER, "position": 100}
    assert manager.is_active is False
