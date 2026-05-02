"""Tests for the v2 → v3 hub + subentries migration."""
from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_WHEN_AWAY_ONLY,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_TIME,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_TTS_MODE,
    CONF_TYPE,
    DAYS,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    MODE_AWAY_ONLY,
    MODE_DISABLED,
    SUBENTRY_TYPE_INSTANCE,
    TYPE_HUB,
)


def _legacy_data(name: str, *, cover: str = "cover.living_room") -> dict:
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


def _legacy_entry(
    *, name: str, entry_id: str, unique_id: str, cover: str = "cover.living_room"
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=name,
        data=_legacy_data(name, cover=cover),
        options={},
        entry_id=entry_id,
        unique_id=unique_id,
        version=2,
    )


async def test_migration_promotes_single_legacy_entry_to_hub(
    hass: HomeAssistant,
) -> None:
    """A lone v2 entry becomes the hub itself with one subentry."""
    legacy = _legacy_entry(name="Bureau", entry_id="legacy_a", unique_id="bureau")
    legacy.add_to_hass(hass)

    assert await hass.config_entries.async_setup(legacy.entry_id)
    await hass.async_block_till_done()

    # The original entry was promoted to a hub (v2→v3), then v3→v4 (notify
    # mode constants), then v4→v5 (presence_simulation split).
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    hub = entries[0]
    assert hub.entry_id == "legacy_a"
    assert hub.version == 5
    assert hub.title == HUB_TITLE
    assert hub.unique_id == HUB_UNIQUE_ID
    assert hub.data[CONF_TYPE] == TYPE_HUB
    assert hub.data[CONF_NOTIFY_SERVICES] == []
    # v3→v4: empty services → mode=disabled; CONF_NOTIFY_WHEN_AWAY_ONLY removed.
    assert hub.data[CONF_NOTIFY_MODE] == MODE_DISABLED
    assert CONF_NOTIFY_WHEN_AWAY_ONLY not in hub.data

    # The instance lives on as the hub's first subentry.
    assert len(hub.subentries) == 1
    subentry = next(iter(hub.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_TYPE_INSTANCE
    assert subentry.title == "Bureau"
    assert subentry.unique_id == "bureau"
    assert subentry.data[CONF_OPEN_TIME] == "08:00:00"
    # CONF_NAME is dropped from subentry.data (lives in title).
    assert CONF_NAME not in subentry.data


async def test_migration_folds_two_legacy_entries_into_one_hub(
    hass: HomeAssistant,
) -> None:
    """Two v2 entries collapse to a single hub with two subentries."""
    bureau = _legacy_entry(
        name="Bureau", entry_id="legacy_a", unique_id="bureau", cover="cover.bureau"
    )
    rdc = _legacy_entry(
        name="RDC", entry_id="legacy_b", unique_id="rdc", cover="cover.rdc"
    )
    bureau.add_to_hass(hass)
    rdc.add_to_hass(hass)

    # Just bring up the integration; both entries will be migrated by
    # async_setup before per-entry setup runs.
    assert await hass.config_entries.async_setup(bureau.entry_id)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1, (
        f"Expected exactly one hub, got {[(e.entry_id, e.title) for e in entries]}"
    )
    hub = entries[0]
    assert hub.version == 5
    assert hub.data[CONF_TYPE] == TYPE_HUB

    titles = sorted(s.title for s in hub.subentries.values())
    assert titles == ["Bureau", "RDC"]

    unique_ids = sorted(s.unique_id for s in hub.subentries.values())
    assert unique_ids == ["bureau", "rdc"]

    # Each subentry preserves its instance config.
    by_title = {s.title: s for s in hub.subentries.values()}
    assert by_title["Bureau"].data[CONF_COVERS] == ["cover.bureau"]
    assert by_title["RDC"].data[CONF_COVERS] == ["cover.rdc"]


async def test_migration_v3_to_v4_converts_boolean_flags(
    hass: HomeAssistant,
) -> None:
    """A v3 hub with boolean away-only flags is migrated to v4 mode constants.

    v3 hub had:
      notify_when_away_only: True  + notify_services non-empty → mode=away_only
      no tts_engine / no tts_targets                            → tts_mode=disabled
    """
    hub = MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data={
            CONF_TYPE: TYPE_HUB,
            CONF_NOTIFY_SERVICES: ["notify.persistent_notification"],
            CONF_NOTIFY_WHEN_AWAY_ONLY: True,
        },
        options={},
        entry_id="native_hub",
        unique_id=HUB_UNIQUE_ID,
        version=3,
    )
    hub.add_to_hass(hass)

    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.entry_id == "native_hub"
    assert entry.version == 5
    assert entry.data[CONF_NOTIFY_SERVICES] == [
        "notify.persistent_notification"
    ]
    assert entry.data[CONF_NOTIFY_MODE] == MODE_AWAY_ONLY
    assert CONF_NOTIFY_WHEN_AWAY_ONLY not in entry.data
    assert entry.data[CONF_TTS_MODE] == MODE_DISABLED


async def test_migration_v4_to_v5_strips_simulation_fields_from_instance(
    hass: HomeAssistant,
) -> None:
    """v4 instance subentries are kept as Planification with simulation fields purged.

    v0.5.0 splits the former mixed ``instance`` subentry into a deterministic
    Planification (still ``subentry_type='instance'``) and a new
    ``presence_simulation`` type. Existing instances become Planification:
    their ``randomize`` / ``random_max_minutes`` / ``only_when_away`` /
    ``presence_entity`` fields are stripped from ``data``.
    """
    from homeassistant.config_entries import ConfigSubentryData

    hub = MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data={
            CONF_TYPE: TYPE_HUB,
            CONF_NOTIFY_SERVICES: [],
            CONF_NOTIFY_MODE: MODE_DISABLED,
        },
        options={},
        entry_id="hub_v4",
        unique_id=HUB_UNIQUE_ID,
        version=4,
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_INSTANCE,
                title="Bureau",
                unique_id="bureau",
                data={
                    CONF_COVERS: ["cover.bureau"],
                    CONF_OPEN_TIME: "08:00:00",
                    CONF_CLOSE_TIME: "20:00:00",
                    CONF_DAYS: list(DAYS),
                    CONF_RANDOMIZE: True,
                    CONF_RANDOM_MAX_MINUTES: 45,
                    CONF_ONLY_WHEN_AWAY: True,
                },
            )
        ],
    )
    hub.add_to_hass(hass)

    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(hub.entry_id)
    assert entry.version == 5

    subentry = next(iter(entry.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_TYPE_INSTANCE
    assert subentry.data[CONF_OPEN_TIME] == "08:00:00"
    assert subentry.data[CONF_CLOSE_TIME] == "20:00:00"
    assert CONF_RANDOMIZE not in subentry.data
    assert CONF_RANDOM_MAX_MINUTES not in subentry.data
    assert CONF_ONLY_WHEN_AWAY not in subentry.data


async def test_migration_reuses_legacy_entry_id_as_subentry_id(
    hass: HomeAssistant,
) -> None:
    """The new subentry must reuse the legacy ``entry_id`` as its ``subentry_id``.

    Entities are now identified by ``subentry.subentry_id`` (their
    ``unique_id`` is ``f"{subentry_id}_next_open"`` etc.). If migration
    generated a brand-new subentry_id, the existing registry entries —
    keyed on the legacy ``entry_id`` — would no longer match and HA
    would create duplicate entities. Reusing the legacy id is the
    cheapest way to preserve registry state.
    """
    bureau = _legacy_entry(
        name="Bureau", entry_id="legacy_bureau", unique_id="bureau"
    )
    rdc = _legacy_entry(
        name="RDC", entry_id="legacy_rdc", unique_id="rdc"
    )
    bureau.add_to_hass(hass)
    rdc.add_to_hass(hass)

    assert await hass.config_entries.async_setup(bureau.entry_id)
    await hass.async_block_till_done()

    hub = hass.config_entries.async_entries(DOMAIN)[0]
    subentry_ids = set(hub.subentries.keys())
    # Both legacy entry_ids survive as the subentry_ids.
    assert subentry_ids == {"legacy_bureau", "legacy_rdc"}


async def test_migration_preserves_unique_id_for_entity_id_stability(
    hass: HomeAssistant,
) -> None:
    """The legacy entry's unique_id must end up as the subentry's unique_id.

    This is the contract that keeps existing user automations working
    after the migration: ``entities._build_entity_id`` derives the
    entity_id prefix from ``source.unique_id``, so as long as that value
    is preserved across the v2 → v3 conversion, sensor/switch/button
    entity_ids stay identical (e.g. ``sensor.bureau_next_open``).
    """
    legacy = _legacy_entry(
        name="Bureau Renamed", entry_id="legacy_x", unique_id="bureau"
    )
    legacy.add_to_hass(hass)

    assert await hass.config_entries.async_setup(legacy.entry_id)
    await hass.async_block_till_done()

    hub = hass.config_entries.async_entries(DOMAIN)[0]
    subentry = next(iter(hub.subentries.values()))
    assert subentry.unique_id == "bureau"


# ---- v0.4.11 residual `model` cleanup ---------------------------------------


async def test_residual_model_is_cleared_on_setup(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Devices with the v0.4.8/v0.4.9 stale `model` are cleaned on next load."""
    device_registry = dr.async_get(hass)
    subentry_id = next(iter(mock_config_entry.subentries))

    # Seed the residual `model` from v0.4.8/v0.4.9.
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, subentry_id)},
        model="Presence schedule",
    )
    assert device.model == "Presence schedule"

    # Reload the hub: the migration should clear it.
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    refreshed = device_registry.async_get(device.id)
    assert refreshed is not None
    assert refreshed.model is None


async def test_user_model_is_preserved_on_setup(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Models that aren't the known stale values must not be wiped."""
    device_registry = dr.async_get(hass)
    subentry_id = next(iter(mock_config_entry.subentries))

    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, subentry_id)},
        model="Custom user value",
    )
    assert device.model == "Custom user value"

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    refreshed = device_registry.async_get(device.id)
    assert refreshed is not None
    assert refreshed.model == "Custom user value"
