"""Tests for the ShuttersScheduler core logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from freezegun import freeze_time
from homeassistant.const import SERVICE_CLOSE_COVER, SERVICE_OPEN_COVER
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.shutters_management import ShuttersScheduler
from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_TIME,
    CONF_PRESENCE_ENTITY,
    DOMAIN,
)


async def test_next_open_and_close_after_now(
    hass: HomeAssistant, setup_integration
) -> None:
    """next_open/next_close must return future timestamps when not paused."""
    scheduler: ShuttersScheduler = setup_integration
    next_open = scheduler.next_open()
    next_close = scheduler.next_close()
    now = dt_util.utcnow()
    assert next_open is not None and next_open > now
    assert next_close is not None and next_close > now


async def test_paused_returns_none(
    hass: HomeAssistant, setup_integration
) -> None:
    """When paused, next_open/next_close must return None."""
    scheduler: ShuttersScheduler = setup_integration
    await scheduler.async_set_paused(True)
    assert scheduler.next_open() is None
    assert scheduler.next_close() is None


async def test_no_active_days_returns_none(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """An empty active-days list must yield no upcoming triggers."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_DAYS: []},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    scheduler: ShuttersScheduler = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert scheduler.next_open() is None
    assert scheduler.next_close() is None


async def test_run_now_open_calls_cover_service(
    hass: HomeAssistant, setup_integration
) -> None:
    """async_run_now('open') must call cover.open_cover with the configured covers."""
    scheduler: ShuttersScheduler = setup_integration
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["cover.living_room"]


async def test_run_now_close_calls_cover_service(
    hass: HomeAssistant, setup_integration
) -> None:
    """async_run_now('close') must call cover.close_cover."""
    scheduler: ShuttersScheduler = setup_integration
    calls = async_mock_service(hass, "cover", SERVICE_CLOSE_COVER)
    await scheduler.async_run_now(ACTION_CLOSE)
    await hass.async_block_till_done()
    assert len(calls) == 1


async def _setup_with_open_at_noon(
    hass: HomeAssistant,
    base_config: dict,
    mock_config_entry,
    *,
    only_when_away: bool,
    presence_entity: str | None,
) -> None:
    """Configure and set up the integration so that the open trigger fires at 12:00 UTC."""
    await hass.config.async_set_time_zone("UTC")
    base_config[CONF_OPEN_TIME] = "12:00:00"
    base_config[CONF_ONLY_WHEN_AWAY] = only_when_away
    if presence_entity is not None:
        base_config[CONF_PRESENCE_ENTITY] = presence_entity
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, data=base_config)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_only_when_away_skips_when_home(
    hass: HomeAssistant, base_config, mock_config_entry
) -> None:
    """only_when_away with a 'home' presence entity must skip the open trigger."""
    hass.states.async_set("person.someone", "home")
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    fake_now = datetime(2026, 4, 27, 11, 59, 0, tzinfo=timezone.utc)
    with freeze_time(fake_now):
        await _setup_with_open_at_noon(
            hass,
            base_config,
            mock_config_entry,
            only_when_away=True,
            presence_entity="person.someone",
        )
        async_fire_time_changed(hass, fake_now + timedelta(seconds=61))
        await hass.async_block_till_done()

    assert calls == []


async def test_only_when_away_runs_when_away(
    hass: HomeAssistant, base_config, mock_config_entry
) -> None:
    """only_when_away with a 'not_home' presence entity must fire the open trigger."""
    hass.states.async_set("person.someone", "not_home")
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    fake_now = datetime(2026, 4, 27, 11, 59, 0, tzinfo=timezone.utc)
    with freeze_time(fake_now):
        await _setup_with_open_at_noon(
            hass,
            base_config,
            mock_config_entry,
            only_when_away=True,
            presence_entity="person.someone",
        )
        async_fire_time_changed(hass, fake_now + timedelta(seconds=61))
        await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["cover.living_room"]


async def test_no_covers_skips_call(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """An empty covers list must short-circuit before calling cover.*."""
    from custom_components.shutters_management.const import CONF_COVERS

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_COVERS: []}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    scheduler: ShuttersScheduler = hass.data[DOMAIN][mock_config_entry.entry_id]

    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()
    assert calls == []
