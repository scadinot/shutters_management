"""Tests for the open / close button entities."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.components.button import SERVICE_PRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    DOMAIN,
    SUBENTRY_TYPE_PRESENCE_SIM,
)

from .conftest import build_hub_with_instance, get_only_subentry_id


def _button_entity_id(
    hass: HomeAssistant, subentry_id: str, action: str
) -> str:
    """Look up the button entity_id by its subentry-scoped unique_id."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{subentry_id}_test_{action}"
    )
    assert entity_id is not None, f"Missing button entity for action: {action}"
    return entity_id


async def test_button_unique_ids_are_subentry_scoped(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Both button unique_ids must include the subentry_id (multi-instance safe)."""
    registry = er.async_get(hass)
    subentry_id = get_only_subentry_id(mock_config_entry)
    for action in (ACTION_OPEN, ACTION_CLOSE):
        expected = f"{subentry_id}_test_{action}"
        assert (
            registry.async_get_entity_id("button", DOMAIN, expected) is not None
        )


async def test_button_entity_ids_are_stable_english(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Resolved entity_ids must use the English slug regardless of locale."""
    registry = er.async_get(hass)
    subentry_id = get_only_subentry_id(mock_config_entry)
    open_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{subentry_id}_test_{ACTION_OPEN}"
    )
    close_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{subentry_id}_test_{ACTION_CLOSE}"
    )
    assert open_id == "button.bureau_open"
    assert close_id == "button.bureau_close"


async def test_button_press_open_calls_run_now(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Pressing the open button must invoke scheduler.async_run_now('open')."""
    scheduler = setup_integration
    subentry_id = get_only_subentry_id(mock_config_entry)
    entity_id = _button_entity_id(hass, subentry_id, ACTION_OPEN)

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
    subentry_id = get_only_subentry_id(mock_config_entry)
    entity_id = _button_entity_id(hass, subentry_id, ACTION_CLOSE)

    with patch.object(
        scheduler, "async_run_now", AsyncMock()
    ) as mock_run_now:
        await hass.services.async_call(
            "button", SERVICE_PRESS, {"entity_id": entity_id}, blocking=True
        )
        mock_run_now.assert_awaited_once_with(ACTION_CLOSE)


async def test_presence_simulation_buttons_use_dedicated_device(
    hass: HomeAssistant, base_config
) -> None:
    """A presence_simulation subentry must produce test buttons on its own device.

    Covers the ``SUBENTRY_TYPE_PRESENCE_SIM`` branch in ``button.py`` setup
    and confirms the platform picks the ``presence_simulation``
    device-translation_key (not the default ``instance``).
    """
    entry = build_hub_with_instance(
        instance_data=base_config,
        instance_title="Présence",
        instance_unique_id="presence",
        subentry_type=SUBENTRY_TYPE_PRESENCE_SIM,
        entry_id="presence_button_entry",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    entity_registry = er.async_get(hass)
    open_id = entity_registry.async_get_entity_id(
        "button", DOMAIN, f"{subentry_id}_test_{ACTION_OPEN}"
    )
    close_id = entity_registry.async_get_entity_id(
        "button", DOMAIN, f"{subentry_id}_test_{ACTION_CLOSE}"
    )
    assert open_id is not None and close_id is not None

    device_registry = dr.async_get(hass)
    open_entry = entity_registry.async_get(open_id)
    device = device_registry.async_get(open_entry.device_id)
    assert device is not None
    assert (DOMAIN, subentry_id) in device.identifiers

    component = hass.data["entity_components"]["button"]
    open_entity = component.get_entity(open_id)
    close_entity = component.get_entity(close_id)
    assert open_entity is not None and close_entity is not None
    assert open_entity.device_info["translation_key"] == "presence_simulation"
    assert close_entity.device_info["translation_key"] == "presence_simulation"
