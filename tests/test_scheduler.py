"""Tests for the ShuttersScheduler core logic."""
from __future__ import annotations

from homeassistant.const import SERVICE_CLOSE_COVER, SERVICE_OPEN_COVER
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.shutters_management import ShuttersScheduler
from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
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


async def test_only_when_away_skips_when_home(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """only_when_away with a 'home' presence entity must skip the trigger."""
    hass.states.async_set("person.someone", "home")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_ONLY_WHEN_AWAY: True,
            CONF_PRESENCE_ENTITY: "person.someone",
        },
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    scheduler: ShuttersScheduler = hass.data[DOMAIN][mock_config_entry.entry_id]

    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    await scheduler._async_trigger(SERVICE_OPEN_COVER, dt_util.utcnow())
    await hass.async_block_till_done()
    assert calls == []


async def test_only_when_away_runs_when_away(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """only_when_away with a 'not_home' presence entity must run the trigger."""
    hass.states.async_set("person.someone", "not_home")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_ONLY_WHEN_AWAY: True,
            CONF_PRESENCE_ENTITY: "person.someone",
        },
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    scheduler: ShuttersScheduler = hass.data[DOMAIN][mock_config_entry.entry_id]

    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    await scheduler._async_trigger(SERVICE_OPEN_COVER, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(calls) == 1


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
