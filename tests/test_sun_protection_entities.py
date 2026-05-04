"""Tests for the v0.6.1 diagnostic entities of the sun_protection groups."""
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


def _build(
    *,
    covers: list[str] | None = None,
    orientation: int = 180,
    arc: int = DEFAULT_ARC,
    min_elevation: int = DEFAULT_MIN_ELEVATION,
    min_uv: int = DEFAULT_MIN_UV,
    target_position: int = DEFAULT_TARGET_POSITION,
    lux_entity: str = "sensor.lux",
    uv_entity: str = "",
    temp_outdoor_entity: str = "sensor.t_ext",
    temp_indoor_entity: str = "",
) -> MockConfigEntry:
    hub_data: dict[str, Any] = {
        CONF_TYPE: TYPE_HUB,
        "notify_services": [],
        "notify_mode": "always",
        CONF_LUX_ENTITY: lux_entity,
        CONF_UV_ENTITY: uv_entity,
        CONF_TEMP_OUTDOOR_ENTITY: temp_outdoor_entity,
    }
    group_data: dict[str, Any] = {
        CONF_COVERS: covers or ["cover.living_room"],
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
        entry_id="test_hub",
        unique_id=HUB_UNIQUE_ID,
        version=6,
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_SUN_PROTECTION,
                title="Salon Sud",
                unique_id="salon_sud",
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


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return next(iter(entry.subentries.keys()))


# ---------------------------------------------------------------------------
# Manager properties (unit-level)
# ---------------------------------------------------------------------------


async def test_azimuth_and_elevation_reflect_sun_state(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=190, elevation=27)
    hass.states.async_set("sensor.lux", "10000")
    _set_sun(hass, azimuth=190, elevation=27)

    entry = _build()
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.azimuth == 190
    assert manager.elevation == 27


async def test_azimuth_diff_handles_wraparound(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    # Orientation = 0 (north), azimuth = 350 → diff should be 10°.
    _set_sun(hass, azimuth=350, elevation=20)
    hass.states.async_set("sensor.lux", "10000")

    entry = _build(orientation=0)
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.azimuth_diff == 10


async def test_is_sun_facing_pure_geometric(hass: HomeAssistant) -> None:
    """Sun in arc + above min_elevation → True regardless of weather."""
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "0")  # pitch dark
    _set_sun(hass, azimuth=180, elevation=30)

    entry = _build(orientation=180, arc=60, min_elevation=15)
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.is_sun_facing is True
    # Out of arc → False.
    _set_sun(hass, azimuth=0, elevation=30)
    assert manager.is_sun_facing is False
    # Below min_elevation → False.
    _set_sun(hass, azimuth=180, elevation=10)
    assert manager.is_sun_facing is False


async def test_lux_close_threshold_reflects_outdoor_temp(
    hass: HomeAssistant,
) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "10000")
    hass.states.async_set("sensor.t_ext", "26")  # standard bracket → 50 000

    entry = _build()
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.lux_close_threshold == 50000

    hass.states.async_set("sensor.t_ext", "32")  # heatwave → 35 000
    assert manager.lux_close_threshold == 35000

    hass.states.async_set("sensor.t_ext", "15")  # too cold → None
    assert manager.lux_close_threshold is None


async def test_lux_close_threshold_none_without_lux_sensor(
    hass: HomeAssistant,
) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.uv", "5")

    entry = _build(
        lux_entity="",
        uv_entity="sensor.uv",
        temp_outdoor_entity="",
    )
    subentry_id = await _setup(hass, entry)
    manager = hass.data[DOMAIN][subentry_id]

    assert manager.lux_close_threshold is None


async def test_pending_seconds_close_debounce(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "80000")
    hass.states.async_set("sensor.t_ext", "26")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        entry = _build()
        subentry_id = await _setup(hass, entry)
        manager = hass.data[DOMAIN][subentry_id]
        # Just after first evaluate: full window remaining.
        assert manager.pending_seconds == LUX_CLOSE_DEBOUNCE_SEC

        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC // 2))
        await manager.async_evaluate()
        assert (
            LUX_CLOSE_DEBOUNCE_SEC // 2 - 1
            <= manager.pending_seconds
            <= LUX_CLOSE_DEBOUNCE_SEC // 2 + 1
        )

        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC // 2 + 5))
        await manager.async_evaluate()
        # Close fired: lux_above_since was reset, no pending now.
        assert manager.pending_seconds == 0


async def test_pending_seconds_open_debounce(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "80000")
    hass.states.async_set("sensor.t_ext", "26")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        entry = _build()
        subentry_id = await _setup(hass, entry)
        manager = hass.data[DOMAIN][subentry_id]
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Lux drops; arm open debounce.
        hass.states.async_set("sensor.lux", "10000")
        await manager.async_evaluate()
        assert manager.pending_seconds == LUX_OPEN_DEBOUNCE_SEC


# ---------------------------------------------------------------------------
# Sensor entities (state surface)
# ---------------------------------------------------------------------------


async def test_status_sensor_reflects_manager_status(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=0, elevation=30)  # out of arc
    hass.states.async_set("sensor.lux", "10000")
    hass.states.async_set("sensor.t_ext", "26")

    entry = _build()
    await _setup(hass, entry)

    state = hass.states.get("sensor.salon_sud_sun_protection_status")
    assert state is not None
    assert state.state == "out_of_arc"


async def test_lux_threshold_sensor(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "10000")
    hass.states.async_set("sensor.t_ext", "32")  # heatwave → 35 000

    entry = _build()
    await _setup(hass, entry)

    state = hass.states.get("sensor.salon_sud_sun_protection_lux_threshold")
    assert state is not None
    assert int(float(state.state)) == 35000


async def test_override_until_sensor_populates_after_manual_move(
    hass: HomeAssistant,
) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set("cover.living_room", "open", {"current_position": 100})
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "80000")
    hass.states.async_set("sensor.t_ext", "26")

    base = datetime(2026, 6, 15, 14, 0, tzinfo=dt_util.UTC)
    with freeze_time(base) as frozen:
        entry = _build()
        subentry_id = await _setup(hass, entry)
        manager = hass.data[DOMAIN][subentry_id]
        frozen.tick(timedelta(seconds=LUX_CLOSE_DEBOUNCE_SEC + 1))
        await manager.async_evaluate()
        assert manager.is_active

        # Manual move (settled at applied 50 → user pulls to 70).
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
    state = hass.states.get("sensor.salon_sud_sun_protection_override_until")
    assert state is not None
    assert state.state != "unknown"
    assert manager.override_until.hour == OVERRIDE_RESET_HOUR


async def test_lux_uv_temp_mirror_sensors(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "55000")
    hass.states.async_set("sensor.uv", "4")
    hass.states.async_set("sensor.t_ext", "27")
    hass.states.async_set("sensor.t_indoor", "24")

    entry = _build(
        uv_entity="sensor.uv",
        temp_indoor_entity="sensor.t_indoor",
    )
    await _setup(hass, entry)

    assert hass.states.get("sensor.salon_sud_sun_protection_lux").state == "55000.0"
    assert hass.states.get("sensor.salon_sud_sun_protection_uv_index").state == "4.0"
    assert (
        hass.states.get("sensor.salon_sud_sun_protection_temp_outdoor").state
        == "27.0"
    )
    assert (
        hass.states.get("sensor.salon_sud_sun_protection_temp_indoor").state
        == "24.0"
    )


async def test_margin_sensors_compute_correct_diff(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=190, elevation=25)
    hass.states.async_set("sensor.lux", "80000")
    hass.states.async_set("sensor.uv", "5")
    hass.states.async_set("sensor.t_ext", "26")

    entry = _build(
        orientation=180,
        min_elevation=15,
        uv_entity="sensor.uv",
        min_uv=3,
    )
    await _setup(hass, entry)

    # azimuth_diff = |190 - 180| = 10
    assert (
        float(
            hass.states.get(
                "sensor.salon_sud_sun_protection_azimuth_diff"
            ).state
        )
        == 10.0
    )
    # elevation_margin = 25 - 15 = 10
    assert (
        float(
            hass.states.get(
                "sensor.salon_sud_sun_protection_elevation_margin"
            ).state
        )
        == 10.0
    )
    # lux_margin = 80000 - 50000 = 30000 (standard bracket)
    assert (
        float(
            hass.states.get(
                "sensor.salon_sud_sun_protection_lux_margin"
            ).state
        )
        == 30000.0
    )
    # uv_margin = 5 - 3 = 2
    assert (
        float(
            hass.states.get(
                "sensor.salon_sud_sun_protection_uv_margin"
            ).state
        )
        == 2.0
    )


async def test_sun_facing_binary_sensor_independent_from_weather(
    hass: HomeAssistant,
) -> None:
    """sun_facing reflects pure geometry, ignoring lux/UV/temp."""
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "100")  # very dark
    hass.states.async_set("sensor.t_ext", "10")  # too cold to close

    entry = _build()
    await _setup(hass, entry)

    state = hass.states.get("binary_sensor.salon_sud_sun_facing")
    assert state is not None
    assert state.state == "on"


async def test_sun_facing_off_when_below_horizon(hass: HomeAssistant) -> None:
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=5)  # below min_elevation=15
    hass.states.async_set("sensor.lux", "80000")
    hass.states.async_set("sensor.t_ext", "26")

    entry = _build()
    await _setup(hass, entry)

    state = hass.states.get("binary_sensor.salon_sud_sun_facing")
    assert state.state == "off"


async def test_lux_margin_unknown_without_threshold(hass: HomeAssistant) -> None:
    """When T_ext < 20 there is no close threshold → lux_margin = unknown."""
    async_mock_service(hass, "cover", "set_cover_position")
    _set_sun(hass, azimuth=180, elevation=30)
    hass.states.async_set("sensor.lux", "80000")
    hass.states.async_set("sensor.t_ext", "15")

    entry = _build()
    await _setup(hass, entry)

    state = hass.states.get("sensor.salon_sud_sun_protection_lux_margin")
    assert state is not None
    assert state.state in ("unknown", "unavailable")
