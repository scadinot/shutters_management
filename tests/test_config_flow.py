"""Tests for the Shutters Management config and options flows."""
from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    CONF_CLOSE_MODE,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_MODE,
    CONF_OPEN_TIME,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    DAYS,
    DEFAULT_CLOSE_MODE,
    DEFAULT_OPEN_MODE,
    DOMAIN,
)


def _valid_step1_input(**overrides):
    """Step-1 payload: everything except per-event time/offset."""
    data = {
        CONF_NAME: "Bureau",
        CONF_COVERS: ["cover.living_room"],
        CONF_OPEN_MODE: DEFAULT_OPEN_MODE,
        CONF_CLOSE_MODE: DEFAULT_CLOSE_MODE,
        CONF_DAYS: list(DAYS),
        CONF_RANDOMIZE: False,
        CONF_RANDOM_MAX_MINUTES: 30,
        CONF_ONLY_WHEN_AWAY: False,
    }
    data.update(overrides)
    return data


def _valid_triggers_input(**overrides):
    """Step-2 payload for two fixed-mode triggers."""
    data = {
        CONF_OPEN_TIME: "08:00:00",
        CONF_CLOSE_TIME: "20:00:00",
    }
    data.update(overrides)
    return data


def _valid_user_input(**overrides):
    """Combined step-1 + step-2 payload (kept for tests still using it)."""
    return {**_valid_step1_input(), **_valid_triggers_input(), **overrides}


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A complete, valid form should walk through both steps and create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_step1_input()
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "triggers"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_triggers_input()
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bureau"
    assert result["data"][CONF_NAME] == "Bureau"
    assert result["data"][CONF_OPEN_TIME] == "08:00:00"
    assert result["data"][CONF_CLOSE_TIME] == "20:00:00"


async def test_user_flow_no_covers_error(hass: HomeAssistant) -> None:
    """Submitting an empty covers list should surface a validation error in step 1."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_step1_input(**{CONF_COVERS: []})
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_COVERS: "no_covers"}


async def test_user_flow_no_days_error(hass: HomeAssistant) -> None:
    """Submitting an empty days list should surface a validation error in step 1."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_step1_input(**{CONF_DAYS: []})
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_DAYS: "no_days"}


async def test_user_flow_confirms_when_no_presence_source(
    hass: HomeAssistant,
) -> None:
    """only_when_away with no person.* and no presence_entity must confirm at step 2."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=_valid_step1_input(**{CONF_ONLY_WHEN_AWAY: True}),
    )
    assert result["step_id"] == "triggers"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_triggers_input()
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm_no_presence"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_flow_edits_configuration(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """The options flow opens on step init then asks for triggers."""
    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=_valid_step1_input()
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "triggers"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_valid_triggers_input(
            **{CONF_OPEN_TIME: "07:30:00", CONF_CLOSE_TIME: "21:30:00"}
        ),
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OPEN_TIME] == "07:30:00"
    assert result["data"][CONF_CLOSE_TIME] == "21:30:00"
    # CONF_NAME is kept out of entry.options so it can't drift from entry.data
    assert CONF_NAME not in result["data"]


async def test_options_flow_rename_keeps_data_in_sync(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Renaming via the options flow must update entry.data[CONF_NAME] and entry.title."""
    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_valid_step1_input(**{CONF_NAME: "Étage"}),
    )
    assert result["step_id"] == "triggers"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=_valid_triggers_input()
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    # entry.data[CONF_NAME] is the canonical name, kept in sync with title
    assert mock_config_entry.data[CONF_NAME] == "Étage"
    assert mock_config_entry.title == "Étage"
    # And entry.options must not carry CONF_NAME (no duplicate)
    assert CONF_NAME not in mock_config_entry.options
