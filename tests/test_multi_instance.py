"""Tests covering the multi-instance support: 1 hub + N instance subentries."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigSubentryData
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
    HUB_TITLE,
    HUB_UNIQUE_ID,
    SUBENTRY_TYPE_INSTANCE,
    signal_state_update,
)

from .conftest import _hub_data, get_only_subentry_id


def _instance_data(*, cover: str = "cover.living_room") -> dict:
    return {
        CONF_COVERS: [cover],
        CONF_OPEN_TIME: "08:00:00",
        CONF_CLOSE_TIME: "20:00:00",
        CONF_DAYS: list(DAYS),
        CONF_RANDOMIZE: False,
        CONF_RANDOM_MAX_MINUTES: 30,
        CONF_ONLY_WHEN_AWAY: False,
    }


def _build_hub_with_two_instances() -> MockConfigEntry:
    """Build a hub holding ``Bureau`` and ``RDC`` instance subentries."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data=_hub_data(),
        options={},
        entry_id="hub_entry_id",
        unique_id=HUB_UNIQUE_ID,
        version=3,
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_INSTANCE,
                title="Bureau",
                unique_id="bureau",
                data=_instance_data(cover="cover.bureau"),
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_INSTANCE,
                title="RDC",
                unique_id="rdc",
                data=_instance_data(cover="cover.rdc"),
            ),
        ],
    )


async def test_two_subentries_can_coexist(hass: HomeAssistant) -> None:
    """Two subentries with distinct names must both load and register entities."""
    hub = _build_hub_with_two_instances()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()

    # Both schedulers live in hass.data, keyed by subentry_id.
    bureau_id, rdc_id = list(hub.subentries.keys())
    assert bureau_id in hass.data[DOMAIN]
    assert rdc_id in hass.data[DOMAIN]

    # 5 entities per instance = 10 total under DOMAIN.
    registry = er.async_get(hass)
    entries = [
        e for e in registry.entities.values() if e.platform == DOMAIN
    ]
    assert len(entries) == 10

    # Entity ids include the instance slug so they don't collide.
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{bureau_id}_next_open"
        )
        == "sensor.bureau_next_open"
    )
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{rdc_id}_next_open"
        )
        == "sensor.rdc_next_open"
    )


async def test_pause_one_subentry_does_not_affect_other(
    hass: HomeAssistant,
) -> None:
    """Pausing scheduler A must not affect scheduler B (signal scoping)."""
    hub = _build_hub_with_two_instances()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()

    bureau_id, rdc_id = list(hub.subentries.keys())
    sched_bureau = hass.data[DOMAIN][bureau_id]
    sched_rdc = hass.data[DOMAIN][rdc_id]

    await sched_bureau.async_set_paused(True)
    await hass.async_block_till_done()

    assert sched_bureau.paused is True
    assert sched_rdc.paused is False


async def test_signal_is_scoped_per_subentry(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """async_set_paused must dispatch a signal scoped to the subentry_id."""
    scheduler = setup_integration
    subentry_id = get_only_subentry_id(mock_config_entry)
    expected_signal = signal_state_update(subentry_id)

    with patch(
        "custom_components.shutters_management.async_dispatcher_send"
    ) as mock_dispatch:
        await scheduler.async_set_paused(True)

    mock_dispatch.assert_called_once_with(hass, expected_signal)
