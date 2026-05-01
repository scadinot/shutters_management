"""Tests for the v2 → v3 hub + subentries migration."""
from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
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
    MODE_ALWAYS,
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

    # The original entry was promoted to a hub (v2→v3) then migrated to v4.
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    hub = entries[0]
    assert hub.entry_id == "legacy_a"
    assert hub.version == 4
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
    assert hub.version == 4
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
    assert entry.version == 4
    assert entry.data[CONF_NOTIFY_SERVICES] == [
        "notify.persistent_notification"
    ]
    assert entry.data[CONF_NOTIFY_MODE] == MODE_AWAY_ONLY
    assert CONF_NOTIFY_WHEN_AWAY_ONLY not in entry.data
    assert entry.data[CONF_TTS_MODE] == MODE_DISABLED


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
