"""Tests for the test_open / test_close button entities."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.components.button import SERVICE_PRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    DOMAIN,
)


def _button_entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, action: str
) -> str:
    """Look up the button entity_id by its scoped unique_id."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_test_{action}"
    )
    assert entity_id is not None, f"Missing button entity for action: {action}"
    return entity_id


async def test_button_unique_ids_are_entry_scoped(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Both button unique_ids must include the entry_id (multi-instance safe)."""
    registry = er.async_get(hass)
    for action in (ACTION_OPEN, ACTION_CLOSE):
        expected = f"{mock_config_entry.entry_id}_test_{action}"
        assert (
            registry.async_get_entity_id("button", DOMAIN, expected) is not None
        )


async def test_button_entity_ids_are_stable_english(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Resolved entity_ids must use the English slug regardless of locale."""
    registry = er.async_get(hass)
    open_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{mock_config_entry.entry_id}_test_{ACTION_OPEN}"
    )
    close_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{mock_config_entry.entry_id}_test_{ACTION_CLOSE}"
    )
    assert open_id == "button.bureau_test_open"
    assert close_id == "button.bureau_test_close"


async def test_button_press_open_calls_run_now(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Pressing the open button must invoke scheduler.async_run_now('open')."""
    scheduler = setup_integration
    entity_id = _button_entity_id(hass, mock_config_entry, ACTION_OPEN)

    with patch.object(
        scheduler, "async_run_now", AsyncMock()
    ) as mock_run_now:
        await hass.services.async_call(
            "button", SERVICE_PRESS, {"entity_id": entity_id}, blocking=True
        )
        mock_run_now.assert_awaited_once_with(ACTION_OPEN)


async def test_button_press_close_calls_run_now(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Pressing the close button must invoke scheduler.async_run_now('close')."""
    scheduler = setup_integration
    entity_id = _button_entity_id(hass, mock_config_entry, ACTION_CLOSE)

    with patch.object(
        scheduler, "async_run_now", AsyncMock()
    ) as mock_run_now:
        await hass.services.async_call(
            "button", SERVICE_PRESS, {"entity_id": entity_id}, blocking=True
        )
        mock_run_now.assert_awaited_once_with(ACTION_CLOSE)
