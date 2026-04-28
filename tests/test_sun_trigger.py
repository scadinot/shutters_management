"""Tests for the sunrise/sunset trigger modes introduced in v0.3.1."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from homeassistant.const import CONF_NAME, SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    CONF_CLOSE_MODE,
    CONF_CLOSE_OFFSET,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_MODE,
    CONF_OPEN_OFFSET,
    CONF_OPEN_TIME,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    DAYS,
    DEFAULT_CLOSE_MODE,
    DOMAIN,
    MODE_FIXED,
    MODE_SUNRISE,
    MODE_SUNSET,
)


def _build_entry(
    *,
    open_mode: str = MODE_FIXED,
    open_offset: int = 0,
    close_mode: str = MODE_FIXED,
    close_offset: int = 0,
    days: list[str] | None = None,
) -> MockConfigEntry:
    """Build a v2 entry with explicit mode/offset settings for sun tests."""
    data = {
        CONF_NAME: "Bureau",
        CONF_COVERS: ["cover.living_room"],
        CONF_OPEN_MODE: open_mode,
        CONF_OPEN_TIME: "08:00:00",
        CONF_OPEN_OFFSET: open_offset,
        CONF_CLOSE_MODE: close_mode,
        CONF_CLOSE_TIME: "20:00:00",
        CONF_CLOSE_OFFSET: close_offset,
        CONF_DAYS: days if days is not None else list(DAYS),
        CONF_RANDOMIZE: False,
        CONF_RANDOM_MAX_MINUTES: 30,
        CONF_ONLY_WHEN_AWAY: False,
    }
    return MockConfigEntry(
        domain=DOMAIN,
        title="Bureau",
        data=data,
        options={},
        entry_id="test_entry_sun",
        unique_id="bureau",
        version=2,
    )


async def test_sunrise_mode_uses_get_astral_event_next(
    hass: HomeAssistant,
) -> None:
    """next_open() must delegate to get_astral_event_next when mode is sunrise."""
    fake_sunrise = datetime(2026, 4, 28, 6, 30, 0, tzinfo=timezone.utc)
    entry = _build_entry(open_mode=MODE_SUNRISE, open_offset=15)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    scheduler = hass.data[DOMAIN][entry.entry_id]
    with patch(
        "custom_components.shutters_management.get_astral_event_next",
        return_value=fake_sunrise,
    ) as mock_next:
        result = scheduler.next_open()

    assert result == fake_sunrise
    args, _ = mock_next.call_args
    assert args[1] == SUN_EVENT_SUNRISE
    # The 4th positional arg is the offset timedelta = 15 minutes.
    assert args[3] == timedelta(minutes=15)


async def test_sunset_offset_negative(
    hass: HomeAssistant,
) -> None:
    """Negative offsets (before sunset) are passed through as a negative timedelta."""
    fake_sunset = datetime(2026, 4, 28, 20, 30, 0, tzinfo=timezone.utc)
    entry = _build_entry(close_mode=MODE_SUNSET, close_offset=-30)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    scheduler = hass.data[DOMAIN][entry.entry_id]
    with patch(
        "custom_components.shutters_management.get_astral_event_next",
        return_value=fake_sunset,
    ) as mock_next:
        result = scheduler.next_close()

    assert result == fake_sunset
    args, _ = mock_next.call_args
    assert args[1] == SUN_EVENT_SUNSET
    assert args[3] == timedelta(minutes=-30)


async def test_sun_handler_filters_inactive_days(
    hass: HomeAssistant,
) -> None:
    """_next_sun must skip inactive days and ask for the next event each time."""
    # Force UTC so the datetimes below map to the expected weekday locally.
    await hass.config.async_set_time_zone("UTC")

    # Active days: only Monday and Tuesday.
    entry = _build_entry(
        open_mode=MODE_SUNRISE,
        open_offset=0,
        days=["mon", "tue"],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    scheduler = hass.data[DOMAIN][entry.entry_id]

    # Sequence of returned datetimes: Sat, Sun, Mon. Only Mon is active.
    sat = datetime(2026, 5, 2, 6, 0, 0, tzinfo=timezone.utc)
    sun = datetime(2026, 5, 3, 6, 0, 0, tzinfo=timezone.utc)
    mon = datetime(2026, 5, 4, 6, 0, 0, tzinfo=timezone.utc)
    with patch(
        "custom_components.shutters_management.get_astral_event_next",
        side_effect=[sat, sun, mon],
    ) as mock_next:
        result = scheduler.next_open()

    assert result == mon
    assert mock_next.call_count == 3


async def test_config_flow_sunrise_path_in_single_panel(
    hass: HomeAssistant,
) -> None:
    """The single-panel form exposes mode + time + offset for both events.

    With open_mode=sunrise, the user enters open_offset and the open_time
    default is preserved; the scheduler will ignore open_time at runtime
    because the mode dispatches to async_track_sunrise.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["step_id"] == "user"

    user_input = {
        CONF_NAME: "Vacances",
        CONF_COVERS: ["cover.living_room"],
        "open": {
            CONF_OPEN_MODE: MODE_SUNRISE,
            CONF_OPEN_TIME: "08:00:00",
            CONF_OPEN_OFFSET: 15,
        },
        "close": {
            CONF_CLOSE_MODE: MODE_FIXED,
            CONF_CLOSE_TIME: "20:00:00",
            CONF_CLOSE_OFFSET: 0,
        },
        CONF_DAYS: list(DAYS),
        CONF_RANDOMIZE: False,
        CONF_RANDOM_MAX_MINUTES: 30,
        CONF_ONLY_WHEN_AWAY: False,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OPEN_MODE] == MODE_SUNRISE
    assert result["data"][CONF_OPEN_OFFSET] == 15
    assert result["data"][CONF_CLOSE_TIME] == "20:00:00"


async def test_unknown_mode_falls_back_safely(
    hass: HomeAssistant, caplog,
) -> None:
    """An unrecognised mode value must not silently default to sunset."""
    entry = _build_entry(open_mode=MODE_FIXED, close_mode=MODE_FIXED)
    # Inject an invalid mode AFTER the fixture builds a valid one — simulates
    # a manual edit of core.config_entries or a future mode rename.
    bad_data = {**entry.data, CONF_OPEN_MODE: "moonrise"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bureau",
        data=bad_data,
        options={},
        entry_id="bad_mode_entry",
        unique_id="bad_mode",
        version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The setup must have succeeded with a warning log for the bad mode.
    assert any(
        "moonrise" in record.message for record in caplog.records
        if record.levelname == "WARNING"
    )

    # next_open() also logs and falls back to fixed → returns a datetime.
    scheduler = hass.data[DOMAIN][entry.entry_id]
    result = scheduler.next_open()
    assert result is not None
