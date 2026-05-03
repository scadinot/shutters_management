"""Tests for the sunrise/sunset trigger modes introduced in v0.3.1."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from homeassistant.const import SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET
from homeassistant.core import HomeAssistant

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
    DOMAIN,
    MODE_FIXED,
    MODE_NONE,
    MODE_SUNRISE,
    MODE_SUNSET,
)

from .conftest import build_hub_with_instance, get_only_subentry_id


def _build_entry(
    *,
    open_mode: str = MODE_FIXED,
    open_offset: int = 0,
    close_mode: str = MODE_FIXED,
    close_offset: int = 0,
    days: list[str] | None = None,
    instance_unique_id: str = "bureau",
):
    """Build a v3 hub with one instance subentry tuned for sun tests."""
    instance_data = {
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
    return build_hub_with_instance(
        instance_data=instance_data,
        instance_unique_id=instance_unique_id,
        entry_id="test_entry_sun",
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

    subentry_id = get_only_subentry_id(entry)
    scheduler = hass.data[DOMAIN][subentry_id]
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

    subentry_id = get_only_subentry_id(entry)
    scheduler = hass.data[DOMAIN][subentry_id]
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

    subentry_id = get_only_subentry_id(entry)
    scheduler = hass.data[DOMAIN][subentry_id]

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


async def test_unknown_mode_falls_back_safely(
    hass: HomeAssistant, caplog,
) -> None:
    """An unrecognised mode value must not silently default to sunset."""
    # Inject an invalid mode at subentry build time.
    entry = _build_entry(open_mode="moonrise")  # type: ignore[arg-type]
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The setup must have succeeded with a warning log for the bad mode.
    assert any(
        "moonrise" in record.message for record in caplog.records
        if record.levelname == "WARNING"
    )

    # next_open() also logs and falls back to fixed → returns a datetime.
    subentry_id = get_only_subentry_id(entry)
    scheduler = hass.data[DOMAIN][subentry_id]
    result = scheduler.next_open()
    assert result is not None


async def test_none_open_mode_registers_no_trigger(
    hass: HomeAssistant,
) -> None:
    """With open_mode=none no time/sun tracker must be registered for opening."""
    entry = _build_entry(open_mode=MODE_NONE, close_mode=MODE_FIXED)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.shutters_management.async_track_time_change"
    ) as mock_time, patch(
        "custom_components.shutters_management.async_track_sunrise"
    ) as mock_rise, patch(
        "custom_components.shutters_management.async_track_sunset"
    ) as mock_set:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_time.assert_called_once()  # only the close trigger (MODE_FIXED)
    mock_rise.assert_not_called()
    mock_set.assert_not_called()


async def test_none_open_mode_next_open_is_none(
    hass: HomeAssistant,
) -> None:
    """next_open() must return None when open_mode is none."""
    entry = _build_entry(open_mode=MODE_NONE)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    scheduler = hass.data[DOMAIN][subentry_id]
    assert scheduler.next_open() is None
    assert scheduler.next_close() is not None


async def test_none_close_mode_next_close_is_none(
    hass: HomeAssistant,
) -> None:
    """next_close() must return None when close_mode is none."""
    entry = _build_entry(close_mode=MODE_NONE)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    scheduler = hass.data[DOMAIN][subentry_id]
    assert scheduler.next_close() is None
    assert scheduler.next_open() is not None
