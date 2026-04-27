"""Tests for async_setup_entry, async_unload_entry and integration services."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    ATTR_ACTION,
    DOMAIN,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_RUN_NOW,
)


async def test_setup_entry_stores_scheduler(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """After setup, hass.data[DOMAIN][entry_id] must hold the scheduler."""
    assert mock_config_entry.entry_id in hass.data[DOMAIN]
    assert hass.data[DOMAIN][mock_config_entry.entry_id] is setup_integration


async def test_setup_entry_registers_entities(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Setup should register 2 sensors + 1 switch + 2 buttons under the entry."""
    registry = er.async_get(hass)
    entries = [
        e
        for e in registry.entities.values()
        if e.config_entry_id == mock_config_entry.entry_id
    ]
    domains = sorted(e.domain for e in entries)
    assert domains == ["button", "button", "sensor", "sensor", "switch"]


async def test_setup_entry_registers_services(
    hass: HomeAssistant, setup_integration
) -> None:
    """Setup should register run_now, pause and resume."""
    assert hass.services.has_service(DOMAIN, SERVICE_RUN_NOW)
    assert hass.services.has_service(DOMAIN, SERVICE_PAUSE)
    assert hass.services.has_service(DOMAIN, SERVICE_RESUME)


async def test_unload_entry_clears_data(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Unloading must remove the scheduler from hass.data and tear down services."""
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.entry_id not in hass.data.get(DOMAIN, {})
    assert not hass.services.has_service(DOMAIN, SERVICE_RUN_NOW)


async def test_service_run_now_calls_scheduler(
    hass: HomeAssistant, setup_integration
) -> None:
    """Calling shutters_management.run_now must invoke scheduler.async_run_now."""
    scheduler = setup_integration
    with patch.object(
        scheduler, "async_run_now", AsyncMock()
    ) as mock_run_now:
        await hass.services.async_call(
            DOMAIN, SERVICE_RUN_NOW, {ATTR_ACTION: ACTION_OPEN}, blocking=True
        )
        mock_run_now.assert_awaited_once_with(ACTION_OPEN)


async def test_service_pause_then_resume(
    hass: HomeAssistant, setup_integration
) -> None:
    """pause then resume must flip the scheduler's paused flag."""
    scheduler = setup_integration

    await hass.services.async_call(DOMAIN, SERVICE_PAUSE, {}, blocking=True)
    assert scheduler.paused is True

    await hass.services.async_call(DOMAIN, SERVICE_RESUME, {}, blocking=True)
    assert scheduler.paused is False


async def test_service_run_now_close(
    hass: HomeAssistant, setup_integration
) -> None:
    """The close action must propagate to the scheduler."""
    scheduler = setup_integration
    with patch.object(
        scheduler, "async_run_now", AsyncMock()
    ) as mock_run_now:
        await hass.services.async_call(
            DOMAIN, SERVICE_RUN_NOW, {ATTR_ACTION: ACTION_CLOSE}, blocking=True
        )
        mock_run_now.assert_awaited_once_with(ACTION_CLOSE)
