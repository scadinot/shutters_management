"""Tests for the Shutters Management config and options flows."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_TIME,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    DAYS,
    DOMAIN,
)


def _valid_user_input(**overrides):
    data = {
        CONF_COVERS: ["cover.living_room"],
        CONF_OPEN_TIME: "08:00:00",
        CONF_CLOSE_TIME: "20:00:00",
        CONF_DAYS: list(DAYS),
        CONF_RANDOMIZE: False,
        CONF_RANDOM_MAX_MINUTES: 30,
        CONF_ONLY_WHEN_AWAY: False,
    }
    data.update(overrides)
    return data


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A complete, valid form should create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_user_input()
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Shutters Management"
    assert result["data"][CONF_OPEN_TIME] == "08:00:00"
    assert result["data"][CONF_CLOSE_TIME] == "20:00:00"


async def test_user_flow_no_covers_error(hass: HomeAssistant) -> None:
    """Submitting an empty covers list should surface a validation error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_user_input(**{CONF_COVERS: []})
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_COVERS: "no_covers"}


async def test_user_flow_no_days_error(hass: HomeAssistant) -> None:
    """Submitting an empty days list should surface a validation error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_user_input(**{CONF_DAYS: []})
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_DAYS: "no_days"}


async def test_user_flow_confirms_when_no_presence_source(
    hass: HomeAssistant,
) -> None:
    """only_when_away with no person.* and no presence_entity must confirm."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=_valid_user_input(**{CONF_ONLY_WHEN_AWAY: True}),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm_no_presence"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_flow_run_open_calls_scheduler(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """The 'run_open' menu entry must invoke scheduler.async_run_now('open')."""
    scheduler = setup_integration
    with patch.object(
        scheduler, "async_run_now", AsyncMock()
    ) as mock_run_now:
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        assert result["type"] == FlowResultType.MENU
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"next_step_id": "run_open"}
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "action_run"
        mock_run_now.assert_awaited_once_with(ACTION_OPEN)


async def test_options_flow_run_close_calls_scheduler(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """The 'run_close' menu entry must invoke scheduler.async_run_now('close')."""
    scheduler = setup_integration
    with patch.object(
        scheduler, "async_run_now", AsyncMock()
    ) as mock_run_now:
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"next_step_id": "run_close"}
        )
        assert result["type"] == FlowResultType.ABORT
        mock_run_now.assert_awaited_once_with(ACTION_CLOSE)


async def test_options_flow_pause_then_resume(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """The pause then resume menu entries must flip scheduler.paused."""
    scheduler = setup_integration

    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "pause_simulation"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "simulation_paused"
    assert scheduler.paused is True

    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "resume_simulation"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "simulation_resumed"
    assert scheduler.paused is False
