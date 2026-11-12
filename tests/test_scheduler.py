"""Tests for the ShuttersScheduler core logic."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from freezegun import freeze_time
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import (
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    STATE_OPEN,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.shutters_management import ShuttersScheduler
from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_ARC,
    CONF_COVERS,
    CONF_DAYS,
    CONF_LUX_ENTITY,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_TIME,
    CONF_ORIENTATION,
    CONF_PRESENCE_ENTITY,
    CONF_SEQUENTIAL_COVERS,
    CONF_TARGET_POSITION,
    CONF_TYPE,
    DEFAULT_ARC,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    DEFAULT_TARGET_POSITION,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    SERVICE_RUN_NOW,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    TYPE_HUB,
)

from .conftest import build_hub_with_instance, get_only_subentry_id


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
    hass: HomeAssistant, base_config
) -> None:
    """An empty active-days list must yield no upcoming triggers."""
    base_config[CONF_DAYS] = []
    entry = build_hub_with_instance(instance_data=base_config)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    scheduler: ShuttersScheduler = hass.data[DOMAIN][subentry_id]
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


async def _setup_with_open_at_noon(
    hass: HomeAssistant,
    base_config: dict,
    *,
    only_when_away: bool,
    presence_entity: str | None,
):
    """Configure and set up a presence-simulation subentry that fires at 12:00 UTC.

    The deterministic ``instance`` schedule ignores ``only_when_away``;
    that gate only matters for the ``presence_simulation`` type. Since
    v0.7.0 ``presence_entity`` lives on the hub and is shared by every
    subentry's mode evaluation.
    """
    await hass.config.async_set_time_zone("UTC")
    base_config[CONF_OPEN_TIME] = "12:00:00"
    base_config[CONF_ONLY_WHEN_AWAY] = only_when_away
    hub_overrides: dict = {}
    if presence_entity is not None:
        hub_overrides[CONF_PRESENCE_ENTITY] = [presence_entity]
    entry = build_hub_with_instance(
        instance_data=base_config,
        hub_data=hub_overrides,
        subentry_type=SUBENTRY_TYPE_PRESENCE_SIM,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_only_when_away_skips_when_home(
    hass: HomeAssistant, base_config
) -> None:
    """only_when_away with a 'home' presence entity must skip the open trigger."""
    hass.states.async_set("person.someone", "home")
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    fake_now = datetime(2026, 4, 27, 11, 59, 0, tzinfo=timezone.utc)
    with freeze_time(fake_now):
        await _setup_with_open_at_noon(
            hass,
            base_config,
            only_when_away=True,
            presence_entity="person.someone",
        )
        async_fire_time_changed(hass, fake_now + timedelta(seconds=61))
        await hass.async_block_till_done()

    assert calls == []


async def test_only_when_away_runs_when_away(
    hass: HomeAssistant, base_config
) -> None:
    """only_when_away with a 'not_home' presence entity must fire the open trigger."""
    hass.states.async_set("person.someone", "not_home")
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    fake_now = datetime(2026, 4, 27, 11, 59, 0, tzinfo=timezone.utc)
    with freeze_time(fake_now):
        await _setup_with_open_at_noon(
            hass,
            base_config,
            only_when_away=True,
            presence_entity="person.someone",
        )
        async_fire_time_changed(hass, fake_now + timedelta(seconds=61))
        await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["cover.living_room"]


async def test_only_when_away_runs_when_the_presence_entity_is_unknown(
    hass: HomeAssistant, base_config
) -> None:
    """An 'unknown' presence entity must not keep the shutters shut.

    The production symptom: ``person.*`` reports ``unknown`` (a restart
    before the device tracker reports, a companion app that dropped its
    tracker), the ``person.*`` fallback hands back that same unusable
    entity, and the scheduled opening is skipped for the whole day.
    """
    hass.states.async_set("person.someone", STATE_UNKNOWN)
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    fake_now = datetime(2026, 4, 27, 11, 59, 0, tzinfo=timezone.utc)
    with freeze_time(fake_now):
        await _setup_with_open_at_noon(
            hass,
            base_config,
            only_when_away=True,
            presence_entity="person.someone",
        )
        async_fire_time_changed(hass, fake_now + timedelta(seconds=61))
        await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["cover.living_room"]


async def test_instance_ignores_only_when_away_even_when_set(
    hass: HomeAssistant, base_config
) -> None:
    """Plain Planification (instance) must trigger regardless of presence.

    The four presence-simulation fields are stripped at runtime for
    ``subentry_type='instance'``; even if leftover ``only_when_away=True``
    persists in storage, the deterministic schedule still fires.
    """
    hass.states.async_set("person.someone", "home")
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    await hass.config.async_set_time_zone("UTC")
    base_config[CONF_OPEN_TIME] = "12:00:00"
    base_config[CONF_ONLY_WHEN_AWAY] = True

    fake_now = datetime(2026, 4, 27, 11, 59, 0, tzinfo=timezone.utc)
    with freeze_time(fake_now):
        entry = build_hub_with_instance(
            instance_data=base_config,
            hub_data={CONF_PRESENCE_ENTITY: ["person.someone"]},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        async_fire_time_changed(hass, fake_now + timedelta(seconds=61))
        await hass.async_block_till_done()

    assert len(calls) == 1


async def test_no_covers_skips_call(
    hass: HomeAssistant, base_config
) -> None:
    """An empty covers list must short-circuit before calling cover.*."""
    base_config[CONF_COVERS] = []
    entry = build_hub_with_instance(instance_data=base_config)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    scheduler: ShuttersScheduler = hass.data[DOMAIN][subentry_id]

    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()
    assert calls == []


async def test_run_now_service_skips_sun_protection_subentries(
    hass: HomeAssistant, base_config
) -> None:
    """The run_now service must not crash when a sun_protection subentry exists.

    Both ShuttersScheduler and ShuttersSunProtectionManager are stored
    under hass.data[DOMAIN], but only the scheduler implements
    ``async_run_now``. The service handler must filter by type so the
    call still works for mixed installs.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data={
            CONF_TYPE: TYPE_HUB,
            "notify_services": [],
            CONF_LUX_ENTITY: "",
        },
        unique_id=HUB_UNIQUE_ID,
        version=8,
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_INSTANCE,
                title="Bureau",
                unique_id="bureau",
                data=dict(base_config),
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_SUN_PROTECTION,
                title="Salon Sud",
                unique_id="salon_sud",
                data={
                    CONF_COVERS: ["cover.salon_sud"],
                    CONF_ORIENTATION: 180,
                    CONF_ARC: DEFAULT_ARC,
                    CONF_MIN_ELEVATION: DEFAULT_MIN_ELEVATION,
                    CONF_MIN_UV: DEFAULT_MIN_UV,
                    CONF_TARGET_POSITION: DEFAULT_TARGET_POSITION,
                },
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    cover_calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    await hass.services.async_call(
        DOMAIN, SERVICE_RUN_NOW, {"action": ACTION_OPEN}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(cover_calls) == 1
    assert cover_calls[0].data["entity_id"] == ["cover.living_room"]


async def test_scheduler_logs_carry_the_submodule_logger_name(
    hass: HomeAssistant, setup_integration, caplog
) -> None:
    """Scheduler log records carry the submodule logger name after the split.

    Consequence of moving ShuttersScheduler out of the package root: records
    that used to be emitted under `custom_components.shutters_management` now
    name the submodule. Users' `logger:` configuration still applies, child
    loggers inheriting from the parent, but the name in the journal changes --
    so it is pinned here rather than left to drift unnoticed.
    """
    scheduler: ShuttersScheduler = setup_integration
    caplog.clear()
    with caplog.at_level(logging.INFO):
        await scheduler.async_set_paused(True)

    names = {record.name for record in caplog.records}
    assert any(
        name.endswith("shutters_management.scheduler") for name in names
    ), names


async def test_sequential_skips_a_cover_reporting_unavailable(
    hass: HomeAssistant, base_config
) -> None:
    """An unavailable cover must be skipped, not called and awaited.

    Core's ``entity_service_call`` silently drops entities whose
    ``available`` is False, so the service call returns without acting
    and the cover never publishes a progress signal. Calling it anyway
    cost a full ``COVER_ACTION_TIMEOUT_SECONDS`` of dead wait before
    the queue moved on. Reproduces the production symptom seen on
    ``cover.volet_bureau`` while its Shelly was off the network.
    """
    base_config[CONF_COVERS] = ["cover.offline_one", "cover.ready_one"]
    entry = build_hub_with_instance(
        instance_data=base_config,
        hub_data={CONF_SEQUENTIAL_COVERS: True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set("cover.offline_one", STATE_UNAVAILABLE)
    hass.states.async_set("cover.ready_one", STATE_OPEN)
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    subentry_id = get_only_subentry_id(entry)
    scheduler: ShuttersScheduler = hass.data[DOMAIN][subentry_id]
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert [call.data["entity_id"] for call in calls] == ["cover.ready_one"]
