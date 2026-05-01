"""Shared fixtures for the Shutters Management test suite."""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_NAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    CONF_CLOSE_MODE,
    CONF_CLOSE_OFFSET,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_WHEN_AWAY_ONLY,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_MODE,
    CONF_OPEN_OFFSET,
    CONF_OPEN_TIME,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_TYPE,
    DAYS,
    DEFAULT_CLOSE_MODE,
    DEFAULT_CLOSE_OFFSET,
    DEFAULT_OPEN_MODE,
    DEFAULT_OPEN_OFFSET,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    SUBENTRY_TYPE_INSTANCE,
    TYPE_HUB,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> Generator[None, None, None]:
    """Enable loading of the integration from custom_components/."""
    yield


@pytest.fixture
def base_config() -> dict[str, Any]:
    """Default instance config dict (without CONF_NAME, which lives in title)."""
    return {
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


def _hub_data(**overrides: Any) -> dict[str, Any]:
    """Default hub entry data (notification settings)."""
    data = {
        CONF_TYPE: TYPE_HUB,
        CONF_NOTIFY_SERVICES: [],
        CONF_NOTIFY_WHEN_AWAY_ONLY: False,
    }
    data.update(overrides)
    return data


def make_subentry_data(
    *,
    title: str = "Bureau",
    unique_id: str = "bureau",
    data: dict[str, Any] | None = None,
) -> ConfigSubentryData:
    """Build a ``ConfigSubentryData`` for an instance subentry."""
    return ConfigSubentryData(
        subentry_type=SUBENTRY_TYPE_INSTANCE,
        title=title,
        unique_id=unique_id,
        data=dict(data) if data is not None else {},
    )


@pytest.fixture
def mock_config_entry(base_config: dict[str, Any]) -> MockConfigEntry:
    """Provide a MockConfigEntry hub with a single ``Bureau`` instance subentry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data=_hub_data(),
        options={},
        entry_id="test_entry_id",
        unique_id=HUB_UNIQUE_ID,
        version=3,
        subentries_data=[
            make_subentry_data(
                title="Bureau",
                unique_id="bureau",
                data=base_config,
            )
        ],
    )


def get_only_subentry_id(entry: MockConfigEntry) -> str:
    """Helper: assert there's exactly one subentry and return its id."""
    subentry_ids = list(entry.subentries.keys())
    assert len(subentry_ids) == 1, (
        f"Expected exactly one subentry, got {len(subentry_ids)}"
    )
    return subentry_ids[0]


def build_hub_with_instance(
    *,
    instance_data: dict[str, Any],
    instance_title: str = "Bureau",
    instance_unique_id: str = "bureau",
    hub_data: dict[str, Any] | None = None,
    entry_id: str = "test_entry_id",
) -> MockConfigEntry:
    """Build a v3 hub MockConfigEntry containing exactly one instance subentry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data=_hub_data(**(hub_data or {})),
        options={},
        entry_id=entry_id,
        unique_id=HUB_UNIQUE_ID,
        version=3,
        subentries_data=[
            make_subentry_data(
                title=instance_title,
                unique_id=instance_unique_id,
                data=instance_data,
            )
        ],
    )


@pytest.fixture
async def setup_integration(hass, mock_config_entry):
    """Add the hub entry to hass and return the only subentry's scheduler."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    subentry_id = get_only_subentry_id(mock_config_entry)
    return hass.data[DOMAIN][subentry_id]
