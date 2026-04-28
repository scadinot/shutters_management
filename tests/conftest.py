"""Shared fixtures for the Shutters Management test suite."""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from homeassistant.const import CONF_NAME
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
    DEFAULT_CLOSE_OFFSET,
    DEFAULT_OPEN_MODE,
    DEFAULT_OPEN_OFFSET,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> Generator[None, None, None]:
    """Enable loading of the integration from custom_components/."""
    yield


@pytest.fixture
def base_config() -> dict[str, Any]:
    """Default config dict matching what the config_flow would persist."""
    return {
        CONF_NAME: "Bureau",
        CONF_COVERS: ["cover.living_room"],
        CONF_OPEN_MODE: DEFAULT_OPEN_MODE,
        CONF_OPEN_TIME: "08:00:00",
        CONF_OPEN_OFFSET: DEFAULT_OPEN_OFFSET,
        CONF_CLOSE_MODE: DEFAULT_CLOSE_MODE,
        CONF_CLOSE_TIME: "20:00:00",
        CONF_CLOSE_OFFSET: DEFAULT_CLOSE_OFFSET,
        CONF_DAYS: list(DAYS),
        CONF_RANDOMIZE: False,
        CONF_RANDOM_MAX_MINUTES: 30,
        CONF_ONLY_WHEN_AWAY: False,
    }


@pytest.fixture
def mock_config_entry(base_config: dict[str, Any]) -> MockConfigEntry:
    """Provide a MockConfigEntry with a stable entry_id."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=base_config[CONF_NAME],
        data=base_config,
        options={},
        entry_id="test_entry_id",
        unique_id="bureau",
        version=2,
    )


@pytest.fixture
async def setup_integration(hass, mock_config_entry):
    """Add the entry to hass and run async_setup_entry; returns the scheduler."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][mock_config_entry.entry_id]
