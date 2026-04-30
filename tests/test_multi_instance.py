"""Tests covering the multi-instance support introduced in v0.3.0."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_TIME,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    DAYS,
    DOMAIN,
    signal_state_update,
)


def _entry_data(name: str, *, cover: str = "cover.living_room") -> dict:
    return {
        CONF_NAME: name,
        CONF_COVERS: [cover],
        CONF_OPEN_TIME: "08:00:00",
        CONF_CLOSE_TIME: "20:00:00",
        CONF_DAYS: list(DAYS),
        CONF_RANDOMIZE: False,
        CONF_RANDOM_MAX_MINUTES: 30,
        CONF_ONLY_WHEN_AWAY: False,
    }


async def test_two_entries_can_coexist(hass: HomeAssistant) -> None:
    """Two config entries with distinct names must both load and register entities."""
    entry_a = MockConfigEntry(
        domain=DOMAIN,
        title="Bureau",
        data=_entry_data("Bureau", cover="cover.bureau"),
        entry_id="entry_a",
        unique_id="bureau",
        version=2,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        title="RDC",
        data=_entry_data("RDC", cover="cover.rdc"),
        entry_id="entry_b",
        unique_id="rdc",
        version=2,
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    for entry in (entry_a, entry_b):
        if entry.state is ConfigEntryState.NOT_LOADED:
            assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Both schedulers live in hass.data, keyed by entry_id.
    assert entry_a.entry_id in hass.data[DOMAIN]
    assert entry_b.entry_id in hass.data[DOMAIN]

    # 5 entities per entry = 10 total under DOMAIN.
    registry = er.async_get(hass)
    entries = [
        e for e in registry.entities.values() if e.platform == DOMAIN
    ]
    assert len(entries) == 10

    # Entity ids include the instance slug so they don't collide.
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry_a.entry_id}_next_open"
        )
        == "sensor.bureau_next_open"
    )
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry_b.entry_id}_next_open"
        )
        == "sensor.rdc_next_open"
    )


async def test_pause_one_entry_does_not_affect_other(
    hass: HomeAssistant,
) -> None:
    """Pausing scheduler A must not affect scheduler B (signal scoping)."""
    entry_a = MockConfigEntry(
        domain=DOMAIN,
        title="Bureau",
        data=_entry_data("Bureau", cover="cover.bureau"),
        entry_id="entry_a",
        unique_id="bureau",
        version=2,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        title="RDC",
        data=_entry_data("RDC", cover="cover.rdc"),
        entry_id="entry_b",
        unique_id="rdc",
        version=2,
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)
    for entry in (entry_a, entry_b):
        if entry.state is ConfigEntryState.NOT_LOADED:
            assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    sched_a = hass.data[DOMAIN][entry_a.entry_id]
    sched_b = hass.data[DOMAIN][entry_b.entry_id]

    await sched_a.async_set_paused(True)
    await hass.async_block_till_done()

    assert sched_a.paused is True
    assert sched_b.paused is False


async def test_signal_is_scoped_per_entry(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """async_set_paused must dispatch a signal scoped to the entry_id."""
    scheduler = setup_integration
    expected_signal = signal_state_update(mock_config_entry.entry_id)

    with patch(
        "custom_components.shutters_management.async_dispatcher_send"
    ) as mock_dispatch:
        await scheduler.async_set_paused(True)

    mock_dispatch.assert_called_once_with(hass, expected_signal)


async def test_migrate_v1_to_v2_injects_conf_name(
    hass: HomeAssistant,
) -> None:
    """A v1 entry without CONF_NAME must be upgraded to v2 with title backfill."""
    legacy = _entry_data("ignored")
    legacy.pop(CONF_NAME)
    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Shutters Management",
        data=legacy,
        entry_id="legacy_entry",
        unique_id=DOMAIN,
        version=1,
    )
    legacy_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(legacy_entry.entry_id)
    await hass.async_block_till_done()

    assert legacy_entry.version == 2
    assert legacy_entry.data[CONF_NAME] == "Shutters Management"
