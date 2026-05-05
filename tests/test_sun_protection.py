"""Tests for the v0.6.0 sun-protection logic (lux + adaptive temperature).

Coverage:

* Helpers ``_close_lux_threshold`` and ``_close_indoor_min``.
* Activation gates (no lux sensor / outdoor too cold / below horizon /
  out of arc / lux too low / room too cool).
* Adaptive lux thresholds (mild / standard / heatwave).
* Hysteresis on arc, elevation, and lux (debounced).
* Manual override and its 04:00 daily reset.
* Switch enable/disable.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any

from freezegun import freeze_time
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.shutters_management.const import (
    ARC_HYSTERESIS_DEG,
    CONF_ARC,
    CONF_COVERS,
    CONF_LUX_ENTITY,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_ORIENTATION,
    CONF_TARGET_POSITION,
    CONF_TEMP_INDOOR_ENTITY,
    CONF_TEMP_OUTDOOR_ENTITY,
    CONF_TYPE,
    CONF_UV_ENTITY,
    DEFAULT_ARC,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    DEFAULT_TARGET_POSITION,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    LUX_CLOSE_DEBOUNCE_SEC,
    LUX_OPEN_DEBOUNCE_SEC,
    OVERRIDE_RESET_HOUR,
    SUBENTRY_TYPE_SUN_PROTECTION,
    TYPE_HUB,
)
from custom_components.shutters_management import ShuttersSunProtectionManager


def _build_hub_with_sun_protection(
    *,
    covers: list[str],
    orientation: int = 180,
    arc: int = DEFAULT_ARC,
    min_elevation: int = DEFAULT_MIN_ELEVATION,
    min_uv: int = DEFAULT_MIN_UV,
    target_position: int = DEFAULT_TARGET_POSITION,
    lux_entity: str = "sensor.lux",
    uv_entity: str = "",
    temp_outdoor_entity: str = "sensor.t_ext",
    temp_indoor_entity: str = "",
    entry_id: str = "test_hub",
    group_title: str = "Salon Sud",
    group_unique_id: str = "salon_sud",
) -> MockConfigEntry:
    """Build a hub MockConfigEntry with one sun-protection subentry."""
    hub_data: dict[str, Any] = {
        CONF_TYPE: TYPE_HUB,
        "notify_services": [],
        "notify_mode": "always",
        CONF_LUX_ENTITY: lux_entity,
        CONF_UV_ENTITY: uv_entity,
        CONF_TEMP_OUTDOOR_ENTITY: temp_outdoor_entity,
    }
    group_data: dict[str, Any] = {
        CONF_COVERS: covers,
        CONF_ORIENTATION: orientation,
        CONF_ARC: arc,
        CONF_MIN_ELEVATION: min_elevation,
        CONF_MIN_UV: min_uv,
        CONF_TARGET_POSITION: target_position,
    }
    if temp_indoor_entity:
        group_data[CONF_TEMP_INDOOR_ENTITY] = temp_indoor_entity

    return MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data=hub_data,
        options={},
        entry_id=entry_id,
        unique_id=HUB_UNIQUE_ID,
        version=8,
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


def _set_lux(hass: HomeAssistant, value: float, entity: str = "sensor.lux") -> None:
    hass.states.async_set(entity, str(value))


def _set_temp(hass: HomeAssistant, value: float, entity: str) -> None:
    hass.states.async_set(entity, str(value))


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Add entry to hass, set up, return subentry_id."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    subentry_ids = list(entry.subentries.keys())
    assert len(subentry_ids) == 1
    return subentry_ids[0]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_close_lux_threshold_below_no_protect_returns_none() -> None:
    assert ShuttersSunProtectionManager._close_lux_threshold(15) is None
    assert ShuttersSunProtectionManager._close_lux_threshold(19.9) is None


def test_close_lux_threshold_brackets() -> None:
    # 20 ≤ T < 24 → mild
    assert ShuttersSunProtectionManager._close_lux_threshold(22) == 70000
    # 24 ≤ T < 30 → standard
    assert ShuttersSunProtectionManager._close_lux_threshold(26) == 50000
    # T ≥ 30 → heatwave
    assert ShuttersSunProtectionManager._close_lux_threshold(32) == 35000


def test_close_lux_threshold_no_outdoor_sensor_falls_back_standard() -> None:
    """Without outdoor temperature, the feature still works with the
    standard threshold so installers without a weather station don't
    lose sun protection entirely."""
    assert ShuttersSunProtectionManager._close_lux_threshold(None) == 50000


def test_close_indoor_min_brackets() -> None:
    assert ShuttersSunProtectionManager._close_indoor_min(None) is None  # no T_ext bypass
    assert ShuttersSunProtectionManager._close_indoor_min(15) is None    # cold
    assert ShuttersSunProtectionManager._close_indoor_min(22) == 24      # mild
    assert ShuttersSunProtectionManager._close_indoor_min(26) == 23      # standard
    assert ShuttersSunProtectionManager._close_indoor_min(32) is None    # heatwave bypass


# ---------------------------------------------------------------------------
# Activation gates (no debounce by default in these short tests because
# they assert *no* close — the debounce only matters when we expect a
# close to fire).
# ---------------------------------------------------------------------------


async def test_no_close_without_any_light_sensor(hass: HomeAssistant) -> None:
    """Without lux *and* without UV the feature is disabled."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        lux_entity="",
        uv_entity="",
        temp_outdoor_entity="",
    )
    subentry_id = await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.status == "no_sensor"
    assert cover_calls == []


async def test_no_close_when_outdoor_too_cold(hass: HomeAssistant) -> None:
    """T_ext < 20 → status temp_too_cold, no activation."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 80000)
    _set_temp(hass, 18, "sensor.t_ext")

    entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
    subentry_id = await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.status == "temp_too_cold"
    assert cover_calls == []


async def test_no_activation_when_azimuth_outside_arc(hass: HomeAssistant) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=0, elevation=30)
    _set_lux(hass, 80000)
    _set_temp(hass, 26, "sensor.t_ext")

    entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
    subentry_id = await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.status == "out_of_arc"
    assert cover_calls == []


async def test_no_activation_below_elevation(hass: HomeAssistant) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=5)
    _set_lux(hass, 80000)
    _set_temp(hass, 26, "sensor.t_ext")

    entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
    subentry_id = await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.status == "below_horizon"
    assert cover_calls == []


# ---------------------------------------------------------------------------
# Adaptive thresholds
# ---------------------------------------------------------------------------


async def test_adaptive_threshold_heatwave(hass: HomeAssistant) -> None:
    """Heatwave (T_ext=32): close fires above 35 000 lux."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 40000)
    _set_temp(hass, 32, "sensor.t_ext")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
        subentry_id = await _setup(hass, entry)
        manager = hass.data[DOMAIN][subentry_id]
        # Pending close after first eval (debounce arming).
        assert manager.status == "pending_close"
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()

    assert any(c.data.get("position") == 50 for c in cover_calls)


async def test_adaptive_threshold_mild_blocks_below_70k(hass: HomeAssistant) -> None:
    """Mid-season (T_ext=22, lux=60 000): below 70 000 → no close."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 60000)
    _set_temp(hass, 22, "sensor.t_ext")

    entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
    subentry_id = await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.status == "lux_too_low"
    assert cover_calls == []


async def test_indoor_temp_blocks_close_in_standard(hass: HomeAssistant) -> None:
    """Standard range with cool room (22°C < 23°C) → no close."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 80000)
    _set_temp(hass, 26, "sensor.t_ext")
    _set_temp(hass, 22, "sensor.t_indoor")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        temp_indoor_entity="sensor.t_indoor",
    )
    subentry_id = await _setup(hass, entry)

    manager = hass.data[DOMAIN][subentry_id]
    assert manager.status == "room_too_cool"
    assert cover_calls == []


async def test_indoor_temp_ignored_in_heatwave(hass: HomeAssistant) -> None:
    """Heatwave: pre-protect even with a cool room."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 80000)
    _set_temp(hass, 32, "sensor.t_ext")
    _set_temp(hass, 22, "sensor.t_indoor")  # cool, would block in standard

    base = datetime(2026, 7, 10, 13, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        entry = _build_hub_with_sun_protection(
            covers=["cover.living_room"],
            temp_indoor_entity="sensor.t_indoor",
        )
        subentry_id = await _setup(hass, entry)
        manager = hass.data[DOMAIN][subentry_id]
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()

    assert any(c.data.get("position") == 50 for c in cover_calls)


# ---------------------------------------------------------------------------
# UV gating (alternative or additive to lux)
# ---------------------------------------------------------------------------


async def test_uv_only_closes_when_above_threshold(hass: HomeAssistant) -> None:
    """No lux sensor, UV ≥ min_uv → close immediately (no debounce)."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.uv", "5")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        lux_entity="",
        uv_entity="sensor.uv",
        temp_outdoor_entity="",
        min_uv=3,
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.is_active
    assert any(c.data.get("position") == 50 for c in cover_calls)


async def test_uv_only_blocks_when_below_threshold(hass: HomeAssistant) -> None:
    """UV-only setup with low UV → status uv_too_low, no close."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.uv", "1")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        lux_entity="",
        uv_entity="sensor.uv",
        temp_outdoor_entity="",
        min_uv=3,
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.status == "uv_too_low"
    assert cover_calls == []


async def test_uv_combined_with_lux_both_must_pass(hass: HomeAssistant) -> None:
    """Lux high but UV below min_uv → no close (UV blocks)."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 80000)
    _set_temp(hass, 26, "sensor.t_ext")
    hass.states.async_set("sensor.uv", "1")  # below min_uv=3

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        uv_entity="sensor.uv",
        min_uv=3,
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.status == "uv_too_low"
    assert cover_calls == []


async def test_uv_drop_during_sun_mode_triggers_exit(hass: HomeAssistant) -> None:
    """In sun mode, UV drops below threshold → immediate exit."""
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 80})
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.uv", "5")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        lux_entity="",
        uv_entity="sensor.uv",
        temp_outdoor_entity="",
        min_uv=3,
        target_position=50,
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_active

    # Simulate cover landing at applied target.
    hass.states.async_set("cover.living_room", "open", {"current_position": 50})

    restore_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("sensor.uv", "1")
    await manager.async_evaluate()

    assert not manager.is_active
    assert any(c.data.get("position") == 80 for c in restore_calls)


# ---------------------------------------------------------------------------
# Unavailable sensor robustness
# ---------------------------------------------------------------------------


async def test_lux_unavailable_blocks_close(hass: HomeAssistant) -> None:
    """If the lux sensor is configured but unknown/unavailable, the close
    path must not fire — lux is the gating signal we cannot evaluate."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "unavailable")
    _set_temp(hass, 26, "sensor.t_ext")

    entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.status == "lux_too_low"
    assert cover_calls == []


async def test_lux_unavailable_during_sun_mode_triggers_exit(
    hass: HomeAssistant,
) -> None:
    """In sun mode, if the lux sensor goes unavailable for the open
    debounce window, the manager exits rather than staying stuck."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        # Sensor goes unknown — lux read returns None.
        hass.states.async_set("sensor.lux", "unknown")
        await manager.async_evaluate()
        assert manager.is_active  # debounce arming, not yet exit

        frozen.tick(timedelta(seconds=LUX_OPEN_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()

    assert not manager.is_active


async def test_uv_unavailable_blocks_close(hass: HomeAssistant) -> None:
    """If the UV sensor is configured but unknown/unavailable, the close
    path must not fire."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.uv", "unavailable")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        lux_entity="",
        uv_entity="sensor.uv",
        temp_outdoor_entity="",
        min_uv=3,
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.status == "uv_too_low"
    assert cover_calls == []


async def test_uv_unavailable_during_sun_mode_triggers_exit(
    hass: HomeAssistant,
) -> None:
    """If the UV sensor disappears while in sun mode, exit immediately
    (UV has no debounce — a lost reading is treated as a failed gate)."""
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 80})
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.uv", "5")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        lux_entity="",
        uv_entity="sensor.uv",
        temp_outdoor_entity="",
        min_uv=3,
        target_position=50,
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]
    assert manager.is_active

    hass.states.async_set("cover.living_room", "open", {"current_position": 50})
    hass.states.async_set("sensor.uv", "unavailable")
    await manager.async_evaluate()

    assert not manager.is_active


async def test_indoor_unavailable_blocks_close(hass: HomeAssistant) -> None:
    """If the user wired an indoor sensor but it is unknown/unavailable,
    the close path must not fire — closing without that comfort signal
    would defeat the configured guarantee."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 80000)
    _set_temp(hass, 26, "sensor.t_ext")
    hass.states.async_set("sensor.t_indoor", "unavailable")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        temp_indoor_entity="sensor.t_indoor",
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.status == "room_too_cool"
    assert cover_calls == []


# ---------------------------------------------------------------------------
# Activation + restoration
# ---------------------------------------------------------------------------


async def _enter_sun_mode(
    hass: HomeAssistant,
    *,
    azimuth: float = 180,
    elevation: float = 30,
    lux: float = 80000,
    t_ext: float = 26,
    t_indoor: float | None = None,
    target_position: int = 50,
    arc: int = DEFAULT_ARC,
    min_elevation: int = DEFAULT_MIN_ELEVATION,
    initial_position: int = 100,
):
    """Bring up the manager in sun mode; return (manager, subentry_id)."""
    hass.states.async_set(
        "cover.living_room", "open", {"current_position": initial_position}
    )
    _set_sun(hass, azimuth=azimuth, elevation=elevation)
    _set_lux(hass, lux)
    _set_temp(hass, t_ext, "sensor.t_ext")
    if t_indoor is not None:
        _set_temp(hass, t_indoor, "sensor.t_indoor")

    entry = _build_hub_with_sun_protection(
        covers=["cover.living_room"],
        orientation=180,
        arc=arc,
        min_elevation=min_elevation,
        target_position=target_position,
        temp_indoor_entity="sensor.t_indoor" if t_indoor is not None else "",
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]
    return manager, subentry_id


async def test_enters_sun_mode_when_conditions_met(hass: HomeAssistant) -> None:
    """All conditions met + debounce passed → covers move to target."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass)
        assert manager.status == "pending_close"
        assert cover_calls == []
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()

    assert manager.is_active
    assert any(c.data.get("position") == 50 for c in cover_calls)


async def test_exits_sun_mode_and_restores_position(hass: HomeAssistant) -> None:
    """Sun leaves arc (with hysteresis margin) → restore snapshot."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, initial_position=80)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # async_mock_service doesn't update HA state; simulate cover at target.
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )

        # Sun far past the extended arc → exit.
        cover_calls = async_mock_service(hass, "cover", "set_cover_position")
        _set_sun(hass, azimuth=0, elevation=30)
        await manager.async_evaluate()
        await hass.async_block_till_done()

    assert not manager.is_active
    assert any(c.data.get("position") == 80 for c in cover_calls)


async def test_no_restore_when_manually_moved(hass: HomeAssistant) -> None:
    """A manual move while in sun mode arms override (no restore)."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, initial_position=80)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Cover settled at applied=50 then user moves it to 70.
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        old_state = hass.states.get("cover.living_room")
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 70}
        )
        new_state = hass.states.get("cover.living_room")

        class FakeEvent:
            data = {
                "entity_id": "cover.living_room",
                "old_state": old_state,
                "new_state": new_state,
            }

        restore_calls = async_mock_service(hass, "cover", "set_cover_position")
        await manager._async_on_cover_state_change(FakeEvent())

    assert manager.override_until is not None
    assert not manager.is_active
    assert all(c.data.get("position") != 80 for c in restore_calls)


# ---------------------------------------------------------------------------
# Hysteresis (arc + elevation)
# ---------------------------------------------------------------------------


async def test_hysteresis_arc_keeps_active_until_extended_arc(
    hass: HomeAssistant,
) -> None:
    """Once active, the arc is widened by ARC_HYSTERESIS_DEG before exit."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, arc=60)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Drift to arc+10° (still inside extended arc=arc+15°).
        _set_sun(hass, azimuth=180 + 60 + 10, elevation=30)
        await manager.async_evaluate()
        assert manager.is_active

        # Drift to arc+ARC_HYSTERESIS_DEG+1 → exit.
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        _set_sun(hass, azimuth=180 + 60 + ARC_HYSTERESIS_DEG + 1, elevation=30)
        await manager.async_evaluate()
        await hass.async_block_till_done()

    assert not manager.is_active


async def test_hysteresis_elevation_keeps_active_below_close_threshold(
    hass: HomeAssistant,
) -> None:
    """Active stays True for a few degrees below min_elevation."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, min_elevation=15)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Drop to 12° (15 - 3, still within hysteresis window of 5°).
        _set_sun(hass, azimuth=180, elevation=12)
        await manager.async_evaluate()
        assert manager.is_active

        # Drop well below: 9° (15 - 6) → exit.
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        _set_sun(hass, azimuth=180, elevation=9)
        await manager.async_evaluate()

    assert not manager.is_active


# ---------------------------------------------------------------------------
# Lux debouncing
# ---------------------------------------------------------------------------


async def test_lux_close_debounce(hass: HomeAssistant) -> None:
    """Lux just above threshold for less than the debounce → no close."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 60000)
    _set_temp(hass, 26, "sensor.t_ext")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
        subentry_id = await _setup(hass, entry)
        manager = hass.data[DOMAIN][subentry_id]

        # Halfway through the debounce: still pending.
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC // 2))
        await manager.async_evaluate()
        assert manager.status == "pending_close"
        assert cover_calls == []

        # Past the debounce: close fires.
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC // 2 + 1))
        await manager.async_evaluate()

    assert any(c.data.get("position") == 50 for c in cover_calls)


async def test_lux_open_debounce(hass: HomeAssistant) -> None:
    """In sun mode, lux drops below LUX_REOPEN: must persist 20 min to exit."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Cloud passes: lux down to 10 000 (well under LUX_REOPEN=25 000).
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        _set_lux(hass, 10000)

        # First low-lux evaluate: arms ``_lux_below_since`` at this instant
        # but doesn't exit yet.
        await manager.async_evaluate()
        assert manager.is_active

        # Halfway through the open-debounce: still active.
        frozen.tick(timedelta(seconds=LUX_OPEN_DEBOUNCE_SEC // 2))
        await manager.async_evaluate()
        assert manager.is_active

        # Past the full open-debounce: exit fires.
        frozen.tick(timedelta(seconds=LUX_OPEN_DEBOUNCE_SEC // 2 + 1))
        await manager.async_evaluate()

    assert not manager.is_active


async def test_indoor_and_outdoor_cool_triggers_reopen(hass: HomeAssistant) -> None:
    """In sun mode, T_indoor < 21 AND T_ext < 22 → exit."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, t_ext=26, t_indoor=25)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Cooling fast (rain): both indoor and outdoor under reopen thresholds.
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        _set_temp(hass, 21, "sensor.t_ext")
        _set_temp(hass, 20, "sensor.t_indoor")
        await manager.async_evaluate()

    assert not manager.is_active


# ---------------------------------------------------------------------------
# Override
# ---------------------------------------------------------------------------


async def test_manual_move_activates_override(hass: HomeAssistant) -> None:
    """A manual cover move arms the override until the next 04:00."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, initial_position=100)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Cover settled at applied=50 then user moves it to 70.
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        old_state = hass.states.get("cover.living_room")
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 70}
        )
        new_state = hass.states.get("cover.living_room")

        class FakeEvent:
            data = {
                "entity_id": "cover.living_room",
                "old_state": old_state,
                "new_state": new_state,
            }

        await manager._async_on_cover_state_change(FakeEvent())

    assert not manager.is_active
    assert manager.status == "override"
    assert manager.override_until is not None
    assert manager.override_until.hour == OVERRIDE_RESET_HOUR
    assert manager.override_until.minute == 0


async def test_override_blocks_evaluation(hass: HomeAssistant) -> None:
    """While override is active, no close even if all conditions are met."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, initial_position=100)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()

        # Arm override via manual move (settled then moved).
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        old_state = hass.states.get("cover.living_room")
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 70}
        )
        new_state = hass.states.get("cover.living_room")

        class FakeEvent:
            data = {
                "entity_id": "cover.living_room",
                "old_state": old_state,
                "new_state": new_state,
            }

        await manager._async_on_cover_state_change(FakeEvent())
        assert manager.override_until is not None

        # Re-evaluate with great close conditions: still blocked.
        cover_calls.clear()
        frozen.tick(timedelta(minutes=15))
        await manager.async_evaluate()

    assert manager.status == "override"
    # No new close call should have fired during the override window.
    assert all(c.data.get("position") != 50 for c in cover_calls)


async def test_override_clears_at_04_00(hass: HomeAssistant) -> None:
    """Daily reset at 04:00 clears the override and re-evaluates."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, initial_position=100)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()

        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        old_state = hass.states.get("cover.living_room")
        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 70}
        )
        new_state = hass.states.get("cover.living_room")

        class FakeEvent:
            data = {
                "entity_id": "cover.living_room",
                "old_state": old_state,
                "new_state": new_state,
            }

        await manager._async_on_cover_state_change(FakeEvent())
        assert manager.override_until is not None

        # Trigger the daily reset callback directly.
        await manager._async_daily_reset(dt_util.now())

    assert manager.override_until is None


# ---------------------------------------------------------------------------
# Switch control
# ---------------------------------------------------------------------------


async def test_switch_disabled_prevents_activation(hass: HomeAssistant) -> None:
    """Disabling the switch → no activation, status disabled."""
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    _set_lux(hass, 80000)
    _set_temp(hass, 26, "sensor.t_ext")

    entry = _build_hub_with_sun_protection(covers=["cover.living_room"])
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    cover_calls.clear()
    manager.set_enabled(False)
    await hass.async_block_till_done()

    assert not manager.is_active
    assert manager.status == "disabled"


async def test_switch_disabled_exits_sun_mode(hass: HomeAssistant) -> None:
    """Disabling while in sun mode triggers exit (restore)."""
    async_mock_service(hass, "cover", "set_cover_position")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        manager, _ = await _enter_sun_mode(hass, initial_position=80)
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        hass.states.async_set(
            "cover.living_room", "open", {"current_position": 50}
        )
        restore_calls = async_mock_service(hass, "cover", "set_cover_position")
        manager.set_enabled(False)
        await hass.async_block_till_done()

    assert not manager.is_active
    assert any(c.data.get("position") == 80 for c in restore_calls)
