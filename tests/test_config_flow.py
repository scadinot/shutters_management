"""Tests for the Shutters Management config and subentry flows."""
from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    CONF_ARC,
    CONF_CLOSE_MODE,
    CONF_CLOSE_OFFSET,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_SERVICES,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_MODE,
    CONF_OPEN_OFFSET,
    CONF_OPEN_TIME,
    CONF_ORIENTATION,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_SEQUENTIAL_COVERS,
    CONF_TARGET_POSITION,
    CONF_TTS_MODE,
    CONF_TTS_TARGETS,
    CONF_TYPE,
    CONF_UV_ENTITY,
    DAYS,
    DEFAULT_ARC,
    DEFAULT_CLOSE_MODE,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    DEFAULT_OPEN_MODE,
    DEFAULT_TARGET_POSITION,
    DOMAIN,
    HUB_TITLE,
    MODE_ALWAYS,
    MODE_AWAY_ONLY,
    MODE_DISABLED,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    TYPE_HUB,
)


def _valid_instance_input(**overrides):
    """Subentry user input matching the section-based Planification schema.

    Planification is the deterministic schedule type; it does not expose the
    presence-simulation fields. Use ``_valid_presence_sim_input`` when testing
    the presence-simulation flow.
    """
    data: dict[str, object] = {
        CONF_NAME: "Bureau",
        CONF_COVERS: ["cover.living_room"],
        "open": {
            CONF_OPEN_MODE: DEFAULT_OPEN_MODE,
            CONF_OPEN_TIME: "08:00:00",
            CONF_OPEN_OFFSET: 0,
        },
        "close": {
            CONF_CLOSE_MODE: DEFAULT_CLOSE_MODE,
            CONF_CLOSE_TIME: "20:00:00",
            CONF_CLOSE_OFFSET: 0,
        },
        CONF_DAYS: list(DAYS),
    }
    open_keys = {CONF_OPEN_MODE, CONF_OPEN_TIME, CONF_OPEN_OFFSET}
    close_keys = {CONF_CLOSE_MODE, CONF_CLOSE_TIME, CONF_CLOSE_OFFSET}
    for key, value in overrides.items():
        if key in open_keys:
            data["open"][key] = value
        elif key in close_keys:
            data["close"][key] = value
        else:
            data[key] = value
    return data


def _valid_presence_sim_input(**overrides):
    """Subentry user input matching the presence-simulation schema.

    Same shape as Planification plus the four simulation fields.
    """
    data = _valid_instance_input(
        **{k: v for k, v in overrides.items() if k != CONF_NAME}
    )
    data[CONF_NAME] = overrides.get(CONF_NAME, "Bureau")
    data.setdefault(CONF_RANDOMIZE, False)
    data.setdefault(CONF_RANDOM_MAX_MINUTES, 30)
    data.setdefault(CONF_ONLY_WHEN_AWAY, False)
    for key in (CONF_RANDOMIZE, CONF_RANDOM_MAX_MINUTES, CONF_ONLY_WHEN_AWAY):
        if key in overrides:
            data[key] = overrides[key]
    return data


# ---- Hub config flow ---------------------------------------------------------


async def test_hub_user_flow_creates_singleton(hass: HomeAssistant) -> None:
    """The hub flow creates one entry with shared notification settings.

    The form is laid out in 2 collapsible HA sections (``notifications``
    and ``voice_announcement``) plus the top-level ``sequential_covers``
    toggle. Each section embeds its own three-state mode selector
    (disabled / always / away_only), so user_input must mirror that shape.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_SEQUENTIAL_COVERS: False,
            "notifications": {
                CONF_NOTIFY_SERVICES: [],
                CONF_NOTIFY_MODE: MODE_ALWAYS,
            },
            "voice_announcement": {
                CONF_TTS_TARGETS: [],
                CONF_TTS_MODE: MODE_DISABLED,
            },
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == HUB_TITLE
    assert result["data"][CONF_TYPE] == TYPE_HUB
    # _normalize_hub flattens the sections back into a flat dict.
    assert result["data"][CONF_NOTIFY_SERVICES] == []
    assert result["data"][CONF_NOTIFY_MODE] == MODE_ALWAYS


async def test_hub_user_flow_aborts_when_already_configured(
    hass: HomeAssistant, setup_integration
) -> None:
    """A second hub creation must abort: HA core enforces single_config_entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_hub_options_flow_updates_notification_settings(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """The hub options flow rewrites entry.data with new notify settings."""
    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SEQUENTIAL_COVERS: False,
            "notifications": {
                CONF_NOTIFY_SERVICES: ["notify.persistent_notification"],
                CONF_NOTIFY_MODE: MODE_AWAY_ONLY,
            },
            "voice_announcement": {
                CONF_TTS_TARGETS: [],
                CONF_TTS_MODE: MODE_DISABLED,
            },
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert mock_config_entry.data[CONF_NOTIFY_SERVICES] == [
        "notify.persistent_notification"
    ]
    assert mock_config_entry.data[CONF_NOTIFY_MODE] == MODE_AWAY_ONLY


# ---- Instance subentry flow --------------------------------------------------


async def test_subentry_user_flow_success(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Adding a new instance subentry to the hub must succeed."""
    initial_count = len(mock_config_entry.subentries)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_INSTANCE),
        context={"source": SOURCE_USER},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_instance_input(**{CONF_NAME: "RDC"}),
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "RDC"

    assert len(mock_config_entry.subentries) == initial_count + 1
    new_subentry = next(
        s for s in mock_config_entry.subentries.values() if s.title == "RDC"
    )
    assert new_subentry.unique_id == "rdc"
    assert new_subentry.data[CONF_OPEN_TIME] == "08:00:00"
    assert CONF_NAME not in new_subentry.data


async def test_subentry_user_flow_no_covers_error(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Submitting an empty covers list surfaces a validation error."""
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_INSTANCE),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_instance_input(
            **{CONF_NAME: "RDC", CONF_COVERS: []}
        ),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_COVERS: "no_covers"}


async def test_subentry_user_flow_no_days_error(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Submitting an empty days list surfaces a validation error."""
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_INSTANCE),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_instance_input(
            **{CONF_NAME: "RDC", CONF_DAYS: []}
        ),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_DAYS: "no_days"}


async def test_subentry_user_flow_aborts_on_duplicate_name(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Reusing an existing subentry name must abort with already_configured."""
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_INSTANCE),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        # The fixture's hub already contains a subentry titled "Bureau".
        user_input=_valid_instance_input(**{CONF_NAME: "Bureau"}),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_subentry_user_flow_aborts_on_title_collision_after_rename(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """A rename can leave a stale unique_id; a new subentry with the renamed
    title must still be rejected on title collision.

    Scenario: the fixture's "Bureau" gets reconfigured to title "Étage"
    (its unique_id stays "bureau" because subentry unique_id is immutable
    on rename). Creating a fresh "Étage" would slugify to "etage", which
    is a different unique_id — but the visible title would clash. The
    flow must abort.
    """
    subentry_id = next(iter(mock_config_entry.subentries))
    result = await mock_config_entry.start_subentry_reconfigure_flow(
        hass, subentry_id
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_instance_input(**{CONF_NAME: "Étage"}),
    )
    assert mock_config_entry.subentries[subentry_id].title == "Étage"

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_INSTANCE),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_instance_input(**{CONF_NAME: "Étage"}),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_subentry_user_flow_confirms_when_no_presence_source(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """only_when_away with no person.* and no presence_entity must confirm.

    The confirm-no-presence step is specific to the presence-simulation
    flow (Planification ignores ``only_when_away``).
    """
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_PRESENCE_SIM),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_presence_sim_input(
            **{CONF_NAME: "RDC", CONF_ONLY_WHEN_AWAY: True}
        ),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm_no_presence"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_subentry_reconfigure_updates_existing(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure flow rewrites an existing subentry's title and data."""
    subentry_id = next(iter(mock_config_entry.subentries))

    result = await mock_config_entry.start_subentry_reconfigure_flow(
        hass, subentry_id
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_instance_input(
            **{CONF_NAME: "Étage", CONF_OPEN_TIME: "07:30:00"}
        ),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated = mock_config_entry.subentries[subentry_id]
    assert updated.title == "Étage"
    assert updated.data[CONF_OPEN_TIME] == "07:30:00"
    assert CONF_NAME not in updated.data


# ---- Presence-simulation subentry flow --------------------------------------


async def test_presence_simulation_subentry_user_flow_success(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Creating a presence-simulation subentry stores the four simulation fields."""
    initial_count = len(mock_config_entry.subentries)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_PRESENCE_SIM),
        context={"source": SOURCE_USER},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_presence_sim_input(
            **{
                CONF_NAME: "Présence",
                CONF_RANDOMIZE: True,
                CONF_RANDOM_MAX_MINUTES: 45,
            }
        ),
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Présence"

    assert len(mock_config_entry.subentries) == initial_count + 1
    new_subentry = next(
        s for s in mock_config_entry.subentries.values()
        if s.title == "Présence"
    )
    assert new_subentry.subentry_type == SUBENTRY_TYPE_PRESENCE_SIM
    assert new_subentry.data[CONF_RANDOMIZE] is True
    assert new_subentry.data[CONF_RANDOM_MAX_MINUTES] == 45
    assert new_subentry.data[CONF_ONLY_WHEN_AWAY] is False


async def test_presence_simulation_subentry_reconfigure_updates_existing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, base_config
) -> None:
    """Reconfigure flow rewrites an existing presence-simulation subentry.

    Distinct from the schedule reconfigure test because the simulation
    handler has its own schema (the four extra fields), abort messages
    and persistence path.
    """
    from custom_components.shutters_management.const import SUBENTRY_TYPE_PRESENCE_SIM as _SIM
    from .conftest import build_hub_with_instance

    sim_data = dict(base_config)
    sim_data[CONF_RANDOMIZE] = False
    sim_data[CONF_RANDOM_MAX_MINUTES] = 30
    sim_data[CONF_ONLY_WHEN_AWAY] = False
    entry = build_hub_with_instance(
        instance_data=sim_data,
        instance_title="Présence",
        instance_unique_id="presence",
        subentry_type=_SIM,
        entry_id="presence_sim_reconf_entry",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_presence_sim_input(
            **{
                CONF_NAME: "Présence renommée",
                CONF_OPEN_TIME: "07:30:00",
                CONF_RANDOMIZE: True,
                CONF_RANDOM_MAX_MINUTES: 60,
            }
        ),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated = entry.subentries[subentry_id]
    assert updated.title == "Présence renommée"
    assert updated.subentry_type == _SIM
    assert updated.data[CONF_OPEN_TIME] == "07:30:00"
    assert updated.data[CONF_RANDOMIZE] is True
    assert updated.data[CONF_RANDOM_MAX_MINUTES] == 60
    assert CONF_NAME not in updated.data


async def test_instance_subentry_does_not_accept_simulation_fields(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Submitting simulation fields to the instance flow must fail validation."""
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_INSTANCE),
        context={"source": SOURCE_USER},
    )
    payload = _valid_instance_input(**{CONF_NAME: "RDC"})
    payload[CONF_RANDOMIZE] = True

    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], user_input=payload
        )


# ---- Sun-protection subentry flow -------------------------------------------


def _valid_sun_protection_input(**overrides):
    """Flat user_input matching the sun-protection subentry schema."""
    data: dict[str, object] = {
        CONF_NAME: "Salon Sud",
        CONF_COVERS: ["cover.living_room"],
        CONF_ORIENTATION: "s",
        CONF_ARC: DEFAULT_ARC,
        CONF_MIN_ELEVATION: DEFAULT_MIN_ELEVATION,
        CONF_MIN_UV: DEFAULT_MIN_UV,
        CONF_TARGET_POSITION: DEFAULT_TARGET_POSITION,
    }
    data.update(overrides)
    return data


async def test_sun_protection_subentry_user_flow_success(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Creating a sun-protection subentry stores normalized data."""
    initial_count = len(mock_config_entry.subentries)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_SUN_PROTECTION),
        context={"source": SOURCE_USER},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_sun_protection_input(),
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salon Sud"

    assert len(mock_config_entry.subentries) == initial_count + 1
    new_subentry = next(
        s for s in mock_config_entry.subentries.values() if s.title == "Salon Sud"
    )
    assert new_subentry.unique_id == "salon_sud"
    # Orientation cardinal "s" normalises to 180 degrees.
    assert new_subentry.data[CONF_ORIENTATION] == 180
    assert new_subentry.data[CONF_ARC] == DEFAULT_ARC
    assert new_subentry.data[CONF_TARGET_POSITION] == DEFAULT_TARGET_POSITION
    assert CONF_NAME not in new_subentry.data


async def test_sun_protection_subentry_user_flow_no_covers_error(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Submitting an empty covers list surfaces a validation error."""
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_SUN_PROTECTION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_sun_protection_input(**{CONF_COVERS: []}),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_COVERS: "no_covers"}


async def test_sun_protection_subentry_user_flow_aborts_on_duplicate_name(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Creating a second group with the same name aborts with already_configured."""
    # Create first group.
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_SUN_PROTECTION),
        context={"source": SOURCE_USER},
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_sun_protection_input(**{CONF_NAME: "Salon"}),
    )

    # Attempt duplicate.
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_SUN_PROTECTION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_sun_protection_input(**{CONF_NAME: "Salon"}),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_sun_protection_subentry_reconfigure_updates_existing(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure flow updates an existing sun-protection subentry."""
    # First create a sun-protection subentry.
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_TYPE_SUN_PROTECTION),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_sun_protection_input(**{CONF_NAME: "Terrasse Est"}),
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    subentry_id = next(
        sid
        for sid, s in mock_config_entry.subentries.items()
        if s.title == "Terrasse Est"
    )

    # Reconfigure: change orientation and target position.
    result = await mock_config_entry.start_subentry_reconfigure_flow(
        hass, subentry_id
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_valid_sun_protection_input(
            **{CONF_NAME: "Terrasse Est", CONF_ORIENTATION: "e", CONF_TARGET_POSITION: 30}
        ),
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated = mock_config_entry.subentries[subentry_id]
    assert updated.data[CONF_ORIENTATION] == 90  # "e" → 90°
    assert updated.data[CONF_TARGET_POSITION] == 30


async def test_hub_user_flow_persists_uv_entity(hass: HomeAssistant) -> None:
    """uv_entity submitted in hub config flow is stored in entry.data."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_SEQUENTIAL_COVERS: False,
            CONF_UV_ENTITY: "sensor.uv_index",
            "notifications": {
                CONF_NOTIFY_SERVICES: [],
                CONF_NOTIFY_MODE: MODE_ALWAYS,
            },
            "voice_announcement": {
                CONF_TTS_TARGETS: [],
                CONF_TTS_MODE: MODE_DISABLED,
            },
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_UV_ENTITY] == "sensor.uv_index"
