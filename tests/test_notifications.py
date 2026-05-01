"""Tests for the v0.4.0 hub-level notification hook."""
from __future__ import annotations

import logging

from homeassistant.const import SERVICE_OPEN_COVER
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.shutters_management import ShuttersScheduler
from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_WHEN_AWAY_ONLY,
    CONF_PRESENCE_ENTITY,
    DOMAIN,
)

from .conftest import build_hub_with_instance, get_only_subentry_id


async def _setup_hub(
    hass: HomeAssistant,
    base_config: dict,
    *,
    notify_services: list[str] | None = None,
    notify_when_away_only: bool = False,
    presence_entity: str | None = None,
) -> tuple[MockConfigEntry, ShuttersScheduler]:
    """Build, register and set up a hub with the requested notify settings."""
    if presence_entity is not None:
        base_config[CONF_PRESENCE_ENTITY] = presence_entity
    hub_overrides: dict = {}
    if notify_services is not None:
        hub_overrides[CONF_NOTIFY_SERVICES] = notify_services
    if notify_when_away_only:
        hub_overrides[CONF_NOTIFY_WHEN_AWAY_ONLY] = True

    entry = build_hub_with_instance(
        instance_data=base_config, hub_data=hub_overrides
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    return entry, hass.data[DOMAIN][subentry_id]


async def test_no_notification_when_services_list_empty(
    hass: HomeAssistant, base_config
) -> None:
    """An empty notify_services list must not trigger any notify call."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")

    _, scheduler = await _setup_hub(hass, base_config)
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert notify_calls == []


async def test_notification_sent_after_open_action(
    hass: HomeAssistant, base_config
) -> None:
    """A configured notify service receives a notification after open."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")
    hass.states.async_set(
        "cover.living_room", "closed", {"friendly_name": "Living Room"}
    )

    _, scheduler = await _setup_hub(
        hass, base_config, notify_services=["notify.iphone"]
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(notify_calls) == 1
    payload = notify_calls[0].data
    assert payload["title"] == "Bureau"
    # Header on its own line, then one cover per line.
    assert payload["message"].splitlines() == [
        "Shutters opened:",
        "Living Room",
    ]


async def test_notification_lists_covers_in_processing_order(
    hass: HomeAssistant, base_config
) -> None:
    """The body must enumerate covers in the order the scheduler fired them."""
    from custom_components.shutters_management.const import (
        CONF_COVERS,
        CONF_SEQUENTIAL_COVERS,
    )

    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")

    base_config[CONF_COVERS] = [
        "cover.left",
        "cover.middle",
        "cover.right",
    ]
    hass.states.async_set("cover.left", "open", {"friendly_name": "Left"})
    hass.states.async_set("cover.middle", "open", {"friendly_name": "Middle"})
    hass.states.async_set("cover.right", "open", {"friendly_name": "Right"})

    from .conftest import build_hub_with_instance

    entry = build_hub_with_instance(
        instance_data=base_config,
        hub_data={
            CONF_NOTIFY_SERVICES: ["notify.iphone"],
            CONF_SEQUENTIAL_COVERS: True,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    scheduler = hass.data[DOMAIN][get_only_subentry_id(entry)]

    # Force a deterministic shuffle so the test is repeatable.
    from unittest.mock import patch

    with patch(
        "custom_components.shutters_management.random.shuffle",
        side_effect=lambda seq: seq.reverse(),
    ):
        await scheduler.async_run_now(ACTION_OPEN)
        await hass.async_block_till_done()

    body_lines = notify_calls[0].data["message"].splitlines()
    # Header + 3 covers in reversed order.
    assert body_lines[0].endswith(":")
    assert body_lines[1:] == ["Right", "Middle", "Left"]


async def test_notification_falls_back_to_entity_id_without_friendly_name(
    hass: HomeAssistant, base_config
) -> None:
    """A cover with no state / no friendly_name renders as its entity_id."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")

    _, scheduler = await _setup_hub(
        hass, base_config, notify_services=["notify.iphone"]
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    body_lines = notify_calls[0].data["message"].splitlines()
    # The fixture's only cover has no state set in this test, so we
    # fall back to the raw entity_id.
    assert body_lines[1:] == ["cover.living_room"]


async def test_notification_sent_after_close_action(
    hass: HomeAssistant, base_config
) -> None:
    """A configured notify service receives a notification after close."""
    async_mock_service(hass, "cover", "close_cover")
    notify_calls = async_mock_service(hass, "notify", "iphone")

    _, scheduler = await _setup_hub(
        hass, base_config, notify_services=["notify.iphone"]
    )
    await scheduler.async_run_now(ACTION_CLOSE)
    await hass.async_block_till_done()

    assert len(notify_calls) == 1


async def test_multiple_services_each_called(
    hass: HomeAssistant, base_config
) -> None:
    """Every configured notify service must receive its own notification."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    iphone_calls = async_mock_service(hass, "notify", "iphone")
    slack_calls = async_mock_service(hass, "notify", "slack")

    _, scheduler = await _setup_hub(
        hass,
        base_config,
        notify_services=["notify.iphone", "notify.slack"],
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(iphone_calls) == 1
    assert len(slack_calls) == 1


async def test_no_notification_when_away_only_and_home(
    hass: HomeAssistant, base_config
) -> None:
    """notify_when_away_only=True + presence detected at home → no notify call."""
    hass.states.async_set("person.someone", "home")
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")

    _, scheduler = await _setup_hub(
        hass,
        base_config,
        notify_services=["notify.iphone"],
        notify_when_away_only=True,
        presence_entity="person.someone",
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert notify_calls == []


async def test_notification_when_away_only_and_away(
    hass: HomeAssistant, base_config
) -> None:
    """notify_when_away_only=True + presence away → notification fires."""
    hass.states.async_set("person.someone", "not_home")
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")

    _, scheduler = await _setup_hub(
        hass,
        base_config,
        notify_services=["notify.iphone"],
        notify_when_away_only=True,
        presence_entity="person.someone",
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(notify_calls) == 1


async def test_notification_message_localized_fr(
    hass: HomeAssistant, base_config
) -> None:
    """When HA is in French, the notification body is in French."""
    hass.config.language = "fr"
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")

    _, scheduler = await _setup_hub(
        hass, base_config, notify_services=["notify.iphone"]
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert notify_calls[0].data["message"].startswith("Volets ouverts :")


async def test_notification_message_localized_en(
    hass: HomeAssistant, base_config
) -> None:
    """When HA is in English, the notification body is in English."""
    hass.config.language = "en"
    async_mock_service(hass, "cover", "close_cover")
    notify_calls = async_mock_service(hass, "notify", "iphone")

    _, scheduler = await _setup_hub(
        hass, base_config, notify_services=["notify.iphone"]
    )
    await scheduler.async_run_now(ACTION_CLOSE)
    await hass.async_block_till_done()

    assert notify_calls[0].data["message"].startswith("Shutters closed:")


async def test_notification_failure_does_not_break_cover_action(
    hass: HomeAssistant, base_config
) -> None:
    """A failing notify integration must not propagate up: cover action wins.

    The cover service is invoked first and unconditionally. Even if the
    subsequent notify call raises (HA core catches it because we use
    ``blocking=False``), the cover call must remain visible to test
    spies — that's the user-visible contract: "notification breakage
    never blocks the shutter action".
    """
    cover_calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    async def _broken_notify(call):
        raise HomeAssistantError("notifier down")

    hass.services.async_register("notify", "broken", _broken_notify)

    _, scheduler = await _setup_hub(
        hass, base_config, notify_services=["notify.broken"]
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(cover_calls) == 1


async def test_invalid_notify_target_logs_warning(
    hass: HomeAssistant, base_config, caplog
) -> None:
    """Malformed targets are skipped with a warning, not raised."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    _, scheduler = await _setup_hub(
        hass,
        base_config,
        notify_services=["malformed", "automation.test"],
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await scheduler.async_run_now(ACTION_OPEN)
        await hass.async_block_till_done()

    messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("malformed" in m for m in messages)
    assert any("automation.test" in m for m in messages)
