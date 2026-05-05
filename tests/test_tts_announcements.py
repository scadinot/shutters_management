"""Tests for the v0.4.3 hub-level TTS announcement hook."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import SERVICE_CLOSE_COVER, SERVICE_OPEN_COVER
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
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_SERVICES,
    CONF_PRESENCE_ENTITY,
    CONF_TTS_ENGINE,
    CONF_TTS_MODE,
    CONF_TTS_TARGETS,
    DOMAIN,
    MODE_ALWAYS,
    MODE_AWAY_ONLY,
    MODE_DISABLED,
    MODE_HOME_ONLY,
)

from .conftest import build_hub_with_instance, get_only_subentry_id


async def _setup_tts_hub(
    hass: HomeAssistant,
    base_config: dict,
    *,
    engine: str | None = "tts.test_engine",
    targets: list[str] | None = None,
    tts_mode: str = MODE_ALWAYS,
    notify_services: list[str] | None = None,
    notify_mode: str = MODE_ALWAYS,
    presence_entity: str | None = None,
) -> tuple[MockConfigEntry, ShuttersScheduler]:
    """Build, register and set up a hub with TTS settings of interest.

    Since v0.7.0 ``tts_mode`` and ``notify_mode`` live on each subentry
    while ``presence_entity`` lives on the hub.
    """
    base_config[CONF_TTS_MODE] = tts_mode
    base_config[CONF_NOTIFY_MODE] = notify_mode

    hub_overrides: dict = {}
    if engine is not None:
        hub_overrides[CONF_TTS_ENGINE] = engine
    hub_overrides[CONF_TTS_TARGETS] = targets if targets is not None else [
        "media_player.kitchen"
    ]
    hub_overrides[CONF_NOTIFY_SERVICES] = notify_services if notify_services is not None else []
    if presence_entity is not None:
        hub_overrides[CONF_PRESENCE_ENTITY] = [presence_entity]

    entry = build_hub_with_instance(
        instance_data=base_config, hub_data=hub_overrides
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    return entry, hass.data[DOMAIN][subentry_id]


async def test_no_tts_when_engine_not_configured(
    hass: HomeAssistant, base_config
) -> None:
    """No engine → no tts.speak call, even with media_player targets set."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(
        hass, base_config, engine=None, targets=["media_player.kitchen"]
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert tts_calls == []


async def test_no_tts_when_targets_empty(
    hass: HomeAssistant, base_config
) -> None:
    """Engine set but no media_players → no announcement."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(
        hass, base_config, engine="tts.cloud", targets=[]
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert tts_calls == []


async def test_no_tts_when_mode_disabled(
    hass: HomeAssistant, base_config
) -> None:
    """mode=disabled must silence TTS even when engine and targets are set."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(
        hass, base_config, engine="tts.cloud", tts_mode=MODE_DISABLED
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert tts_calls == []


async def test_tts_speak_after_open_action(
    hass: HomeAssistant, base_config
) -> None:
    """tts.speak fires with the configured engine, targets and message."""
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")
    hass.states.async_set(
        "cover.living_room", "open", {"friendly_name": "Living Room"}
    )

    _, scheduler = await _setup_tts_hub(
        hass,
        base_config,
        engine="tts.cloud",
        targets=["media_player.kitchen", "media_player.office"],
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(tts_calls) == 1
    payload = tts_calls[0].data
    assert payload["entity_id"] == "tts.cloud"
    assert payload["media_player_entity_id"] == [
        "media_player.kitchen",
        "media_player.office",
    ]
    assert payload["message"] == "Shutters opened: Living Room."


async def test_tts_speak_after_close_action(
    hass: HomeAssistant, base_config
) -> None:
    """Close action is announced with the closed-header."""
    async_mock_service(hass, "cover", SERVICE_CLOSE_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(hass, base_config, engine="tts.cloud")
    await scheduler.async_run_now(ACTION_CLOSE)
    await hass.async_block_till_done()

    assert tts_calls[0].data["message"].startswith("Shutters closed: ")


async def test_tts_message_localized_fr(
    hass: HomeAssistant, base_config
) -> None:
    """When HA is in French, the spoken message is in French."""
    hass.config.language = "fr"
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(hass, base_config, engine="tts.cloud")
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert tts_calls[0].data["message"].startswith("Volets ouverts : ")


async def test_tts_uses_comma_separator_not_newline(
    hass: HomeAssistant, base_config
) -> None:
    """The TTS body never carries newlines (would sound wrong on speakers)."""
    from custom_components.shutters_management.const import CONF_COVERS

    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    base_config[CONF_COVERS] = ["cover.a", "cover.b", "cover.c"]
    hass.states.async_set("cover.a", "open", {"friendly_name": "Salon"})
    hass.states.async_set("cover.b", "open", {"friendly_name": "Cuisine"})
    hass.states.async_set("cover.c", "open", {"friendly_name": "Chambre"})

    _, scheduler = await _setup_tts_hub(
        hass, base_config, engine="tts.cloud"
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    message = tts_calls[0].data["message"]
    assert "\n" not in message
    assert "Salon, Cuisine, Chambre" in message


async def test_tts_when_home_only_skips_when_away(
    hass: HomeAssistant, base_config
) -> None:
    """tts_mode=home_only + presence reports away → no announcement."""
    hass.states.async_set("person.someone", "not_home")
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(
        hass,
        base_config,
        engine="tts.cloud",
        tts_mode=MODE_HOME_ONLY,
        presence_entity="person.someone",
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert tts_calls == []


async def test_tts_when_home_only_runs_at_home(
    hass: HomeAssistant, base_config
) -> None:
    """tts_mode=home_only + presence at home → announcement fires."""
    hass.states.async_set("person.someone", "home")
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(
        hass,
        base_config,
        engine="tts.cloud",
        tts_mode=MODE_HOME_ONLY,
        presence_entity="person.someone",
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(tts_calls) == 1


async def test_tts_and_notify_have_independent_modes(
    hass: HomeAssistant, base_config
) -> None:
    """The two channel modes must be evaluated independently.

    Scenario: notify_mode=away_only (silent at home) +
    tts_mode=always (always speak), at home → push must be skipped,
    TTS must still fire.
    """
    hass.states.async_set("person.someone", "home")
    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    notify_calls = async_mock_service(hass, "notify", "iphone")
    tts_calls = async_mock_service(hass, "tts", "speak")

    _, scheduler = await _setup_tts_hub(
        hass,
        base_config,
        engine="tts.cloud",
        tts_mode=MODE_ALWAYS,
        notify_services=["notify.iphone"],
        notify_mode=MODE_AWAY_ONLY,
        presence_entity="person.someone",
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert notify_calls == []
    assert len(tts_calls) == 1


async def test_tts_failure_does_not_break_cover_action(
    hass: HomeAssistant, base_config
) -> None:
    """A failing TTS provider must not propagate up: cover action wins."""
    cover_calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)

    async def _broken_tts(call):
        raise HomeAssistantError("tts down")

    hass.services.async_register("tts", "speak", _broken_tts)

    _, scheduler = await _setup_tts_hub(
        hass, base_config, engine="tts.broken"
    )
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(cover_calls) == 1


async def test_no_tts_if_scheduler_unloaded_mid_call(
    hass: HomeAssistant, base_config
) -> None:
    """If the scheduler is torn down mid-sequence, no announcement fires.

    Symmetric to the existing push-side test in ``test_notifications.py``:
    ``_async_call`` short-circuits both notifications *and* the TTS
    branch when the scheduler is no longer in ``hass.data``.
    """
    from custom_components.shutters_management.const import (
        CONF_COVERS,
        CONF_SEQUENTIAL_COVERS,
    )

    async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    tts_calls = async_mock_service(hass, "tts", "speak")

    base_config[CONF_COVERS] = ["cover.a"]
    base_config[CONF_TTS_MODE] = MODE_ALWAYS
    entry = build_hub_with_instance(
        instance_data=base_config,
        hub_data={
            CONF_TTS_ENGINE: "tts.cloud",
            CONF_TTS_TARGETS: ["media_player.kitchen"],
            CONF_SEQUENTIAL_COVERS: True,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    subentry_id = get_only_subentry_id(entry)
    scheduler = hass.data[DOMAIN][subentry_id]

    async def _evict(*_args, **_kwargs):
        hass.data[DOMAIN].pop(subentry_id, None)

    with patch.object(
        scheduler, "_async_call_sequential", side_effect=_evict
    ):
        await scheduler.async_run_now(ACTION_OPEN)
        await hass.async_block_till_done()

    assert tts_calls == []
