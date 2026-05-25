"""Tests for the Lovelace sidebar panel built by ``panel.py``."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    CONF_ARC,
    CONF_COVERS,
    CONF_LUX_ENTITY,
    CONF_MIN_ELEVATION,
    CONF_ORIENTATION,
    CONF_TARGET_POSITION,
    CONF_TEMP_OUTDOOR_ENTITY,
    CONF_TYPE,
    CONF_UV_ENTITY,
    DEFAULT_ARC,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    TYPE_HUB,
)
from custom_components.shutters_management.panel import (
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    _view_path,
    build_dashboard_config,
)


# ---------------------------------------------------------------------------
# Dashboard structure
# ---------------------------------------------------------------------------


def _hub_with_subentries(
    *, subentries: list[ConfigSubentryData], entry_id: str = "hub_id"
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data={
            CONF_TYPE: TYPE_HUB,
            "notify_services": [],
            CONF_LUX_ENTITY: "sensor.lux",
            CONF_UV_ENTITY: "sensor.uv",
            CONF_TEMP_OUTDOOR_ENTITY: "sensor.t_ext",
        },
        options={},
        entry_id=entry_id,
        unique_id=HUB_UNIQUE_ID,
        version=8,
        subentries_data=subentries,
    )


def _schedule_sub(title: str, unique_id: str) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type=SUBENTRY_TYPE_INSTANCE,
        title=title,
        unique_id=unique_id,
        data={CONF_COVERS: ["cover.demo"]},
    )


def _sim_sub(title: str, unique_id: str) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type=SUBENTRY_TYPE_PRESENCE_SIM,
        title=title,
        unique_id=unique_id,
        data={CONF_COVERS: ["cover.demo"]},
    )


def _sun_sub(title: str, unique_id: str) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type=SUBENTRY_TYPE_SUN_PROTECTION,
        title=title,
        unique_id=unique_id,
        data=MappingProxyType(
            {
                CONF_COVERS: ["cover.salon"],
                CONF_ORIENTATION: 180,
                CONF_ARC: DEFAULT_ARC,
                CONF_MIN_ELEVATION: 15,
                CONF_TARGET_POSITION: 30,
            }
        ),
    )


async def test_dashboard_has_cockpit_and_one_view_per_subentry(
    hass: HomeAssistant,
) -> None:
    """A hub with 1 schedule + 1 sim + 2 suns yields 1 cockpit + 4 views."""
    entry = _hub_with_subentries(
        subentries=[
            _schedule_sub("Bureau", "bureau"),
            _sim_sub("Salon", "salon"),
            _sun_sub("Salon Sud", "salon_sud"),
            _sun_sub("Toiture Ouest", "toiture_ouest"),
        ]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)

    assert config["title"] == PANEL_TITLE
    views = config["views"]
    assert len(views) == 1 + 4
    assert views[0]["path"] == "cockpit"
    paths = [v["path"] for v in views[1:]]
    assert paths == ["bureau", "salon", "salon_sud", "toiture_ouest"]


async def test_dashboard_empty_hub_shows_hint(hass: HomeAssistant) -> None:
    """No subentries → cockpit displays the no_subentries markdown card."""
    entry = _hub_with_subentries(subentries=[])
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)

    cockpit = config["views"][0]
    contents = " ".join(
        c.get("content", "")
        for c in cockpit["cards"]
        if c.get("type") == "markdown"
    )
    # In English (default test config) or French — both mention "sub-entry"
    # / "sous-entrée".
    assert "sub-entry" in contents or "sous-entrée" in contents


def _flatten_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk Lovelace card containers (vertical/horizontal-stack, grid, conditional)."""
    out: list[dict[str, Any]] = []
    for card in cards:
        out.append(card)
        if card.get("type") in ("vertical-stack", "horizontal-stack", "grid"):
            out.extend(_flatten_cards(card.get("cards", [])))
        elif card.get("type") == "conditional":
            inner = card.get("card")
            if inner is not None:
                out.extend(_flatten_cards([inner]))
    return out


async def test_sun_protection_view_has_sun_map_and_gauges(
    hass: HomeAssistant,
) -> None:
    """The drill-down view embeds the 3D custom card + gauges."""
    entry = _hub_with_subentries(
        subentries=[_sun_sub("Salon Sud", "salon_sud")]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    sun_view = next(v for v in config["views"] if v["path"] == "salon_sud")
    all_cards = _flatten_cards(sun_view["cards"])

    # The sun map is now the custom Lovelace card registered via
    # add_extra_js_url. The card receives `hass` from the runtime and
    # reads sun.sun directly — no token, no REST.
    custom_cards = [
        c for c in all_cards
        if c.get("type") == "custom:shutters-sun-3d-card"
    ]
    assert len(custom_cards) == 1
    card = custom_cards[0]
    assert card["subentry_prefix"] == "salon_sud"
    assert card["orientation"] == 180
    assert card["arc"] == DEFAULT_ARC
    # Cover entity ids must be propagated to the card so the JS can
    # aggregate their real state (otherwise the "Volet" overlay falls
    # back to the sun-only heuristic and shows "Ouvert" at night).
    assert card["covers"] == ["cover.salon"]
    assert card["min_elevation"] == 15

    # Four gauges (with lux + UV configured in _hub_with_subentries),
    # nested inside a vertical-stack > horizontal-stack so the section
    # title and the gauges row stay grouped in the same column.
    gauges = [c for c in all_cards if c.get("type") == "gauge"]
    gauge_entities = {g["entity"] for g in gauges}
    assert gauge_entities == {
        "sensor.salon_sud_sun_protection_lux_margin",
        "sensor.salon_sud_sun_protection_elevation_margin",
        "sensor.salon_sud_sun_protection_uv_margin",
        "sensor.salon_sud_sun_protection_azimuth_diff",
    }

    # With lux configured at the hub, the history-graph card must be
    # present and include the lux sensor as a series — otherwise the
    # conditional history-graph logic could regress unnoticed.
    history_cards = [
        c for c in all_cards if c["type"] == "history-graph"
    ]
    assert len(history_cards) == 1
    assert (
        "sensor.salon_sud_sun_protection_lux"
        in history_cards[0]["entities"]
    )


async def test_sun_protection_view_omits_lux_uv_without_sensors(
    hass: HomeAssistant,
) -> None:
    """No lux + no UV at hub → corresponding gauges and history skipped."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        data={
            CONF_TYPE: TYPE_HUB,
            "notify_services": [],
            # Both lux and UV omitted: only sun-position-derived gauges
            # should remain.
            CONF_LUX_ENTITY: "",
            CONF_UV_ENTITY: "",
            CONF_TEMP_OUTDOOR_ENTITY: "sensor.t_ext",
        },
        options={},
        entry_id="hub_no_lux",
        unique_id=HUB_UNIQUE_ID,
        version=8,
        subentries_data=[_sun_sub("Salon Sud", "salon_sud")],
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    sun_view = next(v for v in config["views"] if v["path"] == "salon_sud")
    all_cards = _flatten_cards(sun_view["cards"])

    gauges = [c for c in all_cards if c.get("type") == "gauge"]
    gauge_entities = {g["entity"] for g in gauges}
    assert gauge_entities == {
        "sensor.salon_sud_sun_protection_elevation_margin",
        "sensor.salon_sud_sun_protection_azimuth_diff",
    }
    # Without a lux series (and no temp_indoor in this fixture), the
    # history-graph card is omitted entirely.
    assert not any(
        c["type"] == "history-graph" for c in all_cards
    )


async def test_sun_protection_view_groups_margins_in_vertical_stack(
    hass: HomeAssistant,
) -> None:
    """The margins title and gauges live in a single vertical-stack.

    Otherwise Lovelace's auto-column layout drops the title and the
    gauges into separate columns (regression seen in v0.8.2 — title
    orphaned in the middle column, gauges alone in the right column).
    """
    entry = _hub_with_subentries(
        subentries=[_sun_sub("Salon Sud", "salon_sud")]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    sun_view = next(v for v in config["views"] if v["path"] == "salon_sud")

    # Find a top-level vertical-stack whose first card is the margins
    # markdown title and whose second card is a horizontal-stack of
    # gauges. ``next`` raises StopIteration if no such block exists,
    # which surfaces as a clean test failure.
    margins_block = next(
        c
        for c in sun_view["cards"]
        if c.get("type") == "vertical-stack"
        and len(c.get("cards", [])) >= 2
        and c["cards"][0].get("type") == "markdown"
        and c["cards"][0].get("content", "").startswith("### ")
        and (
            "Marges" in c["cards"][0]["content"]
            or "Margins" in c["cards"][0]["content"]
        )
    )
    inner = margins_block["cards"]
    assert len(inner) >= 2, "vertical-stack must have title + gauges row"
    assert inner[1]["type"] == "horizontal-stack"
    # Each gauge is wrapped in a ``conditional`` card (since v0.9.6)
    # so it disappears when the underlying margin sensor is unknown
    # (e.g. lux_margin while temp_outdoor < T_OUTDOOR_NO_PROTECT).
    for wrapper in inner[1]["cards"]:
        assert wrapper["type"] == "conditional"
        assert wrapper["card"]["type"] == "gauge"


async def test_margin_gauges_wrapped_in_conditional(
    hass: HomeAssistant,
) -> None:
    """Each margin gauge sits inside a conditional card that hides it
    when the entity reports ``unknown`` or ``unavailable``.

    Regression coverage for v0.9.5: cold weather makes
    ``lux_close_threshold`` return ``None``, so
    ``sensor.<g>_sun_protection_lux_margin.state == 'unknown'`` and a
    bare ``gauge`` card surfaces « L'entité n'est pas numérique ».
    """
    entry = _hub_with_subentries(
        subentries=[_sun_sub("Salon Sud", "salon_sud")]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    sun_view = next(v for v in config["views"] if v["path"] == "salon_sud")
    all_cards = _flatten_cards(sun_view["cards"])

    gauges = [c for c in all_cards if c.get("type") == "gauge"]
    assert gauges, "expected at least one margin gauge"
    conditionals = [c for c in all_cards if c.get("type") == "conditional"]
    # Every gauge is wrapped exactly once.
    assert len(conditionals) == len(gauges)
    for cond in conditionals:
        assert cond["card"]["type"] == "gauge"
        entity = cond["card"]["entity"]
        # Both ``unknown`` and ``unavailable`` must be filtered out.
        state_nots = {c.get("state_not") for c in cond["conditions"]}
        assert state_nots == {"unknown", "unavailable"}
        for c in cond["conditions"]:
            assert c["entity"] == entity


async def test_cockpit_sun_tile_is_glance_with_summary(
    hass: HomeAssistant,
) -> None:
    """Each sun-protection tile in the cockpit is a glance card
    summarizing status, lux, sun_facing and elevation.

    Replaces the legacy ``tile`` card so the user can read the key
    state without opening the drill-down. The whole glance stays
    clickable to navigate, just like the tile did.
    """
    entry = _hub_with_subentries(
        subentries=[_sun_sub("Salon Sud", "salon_sud")]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    cockpit = next(v for v in config["views"] if v["path"] == "cockpit")
    cockpit_cards = _flatten_cards(cockpit["cards"])

    glance_cards = [
        c for c in cockpit_cards
        if c.get("type") == "glance" and c.get("title") == "Salon Sud"
    ]
    assert len(glance_cards) == 1
    glance = glance_cards[0]
    nav = glance["tap_action"]
    assert nav["action"] == "navigate"
    assert nav["navigation_path"] == f"/{PANEL_URL_PATH}/salon_sud"
    entity_ids = [e["entity"] for e in glance["entities"]]
    assert entity_ids == [
        "sensor.salon_sud_sun_protection_status",
        "sensor.salon_sud_sun_protection_lux",
        "binary_sensor.salon_sud_sun_facing",
        "sensor.salon_sud_sun_protection_sun_elevation",
    ]
    # Each entity must carry its own tap_action: navigate. HA's
    # ``glance`` card otherwise falls back to ``more-info`` per
    # entity, which would intercept clicks and pop up the entity
    # dialog instead of opening the drill-down.
    for ent in glance["entities"]:
        assert ent["tap_action"]["action"] == "navigate"
        assert ent["tap_action"]["navigation_path"] == nav["navigation_path"]


async def test_cockpit_lists_all_configured_covers(
    hass: HomeAssistant,
) -> None:
    """The cockpit lists every cover from every subentry, deduplicated
    and sorted, so the user has one-click access to each shutter."""
    schedule = ConfigSubentryData(
        subentry_type=SUBENTRY_TYPE_INSTANCE,
        title="Bureau",
        unique_id="bureau",
        data={CONF_COVERS: ["cover.bureau", "cover.salon"]},
    )
    sun = _sun_sub("Salon Sud", "salon_sud")  # CONF_COVERS: ["cover.salon"]
    entry = _hub_with_subentries(subentries=[schedule, sun])
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    cockpit = next(v for v in config["views"] if v["path"] == "cockpit")
    # The covers list now lives inside a vertical-stack (the section
    # « Volets configurés » keeps its title + entities together so
    # Lovelace's auto-column layout does not split them). Flatten to
    # reach it.
    cockpit_cards = _flatten_cards(cockpit["cards"])

    entities_cards = [
        c for c in cockpit_cards if c.get("type") == "entities"
    ]
    cover_lists = [
        c["entities"] for c in entities_cards
        if c.get("entities")
        and all(
            isinstance(e, str) and e.startswith("cover.")
            for e in c["entities"]
        )
    ]
    assert cover_lists, "expected a covers-only entities card in cockpit"
    assert cover_lists[0] == ["cover.bureau", "cover.salon"]


async def test_cockpit_sections_wrapped_in_vertical_stack(
    hass: HomeAssistant,
) -> None:
    """Each cockpit section (title + content) lives inside a single
    vertical-stack so Lovelace's auto-column layout cannot orphan
    the « Planifications » / « Simulations » / « Protections solaires »
    / « Volets configurés » titles in a different column from their
    cards. Same fix pattern as the « Marges » section in v0.8.3.
    """
    entry = _hub_with_subentries(
        subentries=[
            _schedule_sub("Bureau", "bureau"),
            _sim_sub("Salon", "salon"),
            _sun_sub("Salon Sud", "salon_sud"),
        ]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    cockpit = next(v for v in config["views"] if v["path"] == "cockpit")

    # Helper: find every top-level vertical-stack whose first card is
    # a markdown ``### …`` heading. The cockpit has one per section.
    section_stacks = [
        c for c in cockpit["cards"]
        if c.get("type") == "vertical-stack"
        and len(c.get("cards", [])) >= 2
        and c["cards"][0].get("type") == "markdown"
        and c["cards"][0].get("content", "").startswith("### ")
    ]
    # 4 sections: schedules + sims + suns + all_covers.
    assert len(section_stacks) == 4
    # Each stack's second card is the actual content (grid or entities).
    second_types = {s["cards"][1].get("type") for s in section_stacks}
    assert second_types <= {"grid", "entities"}


async def test_sun_protection_view_has_decision_parameters_markdown(
    hass: HomeAssistant,
) -> None:
    """The drill-down sun protection view carries a comprehensive
    « Paramètres de décision » markdown card with current values and
    static thresholds for every gate."""
    entry = _hub_with_subentries(
        subentries=[_sun_sub("Salon Sud", "salon_sud")]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    sun_view = next(v for v in config["views"] if v["path"] == "salon_sud")
    all_cards = _flatten_cards(sun_view["cards"])

    # The header is localized by ``_labels(hass)``; depending on the
    # test environment language (default ``en``) the section title
    # will be in EN or FR. Match either.
    md_cards = [
        c for c in all_cards
        if c.get("type") == "markdown"
        and (
            "Paramètres de décision" in c.get("content", "")
            or "Decision parameters" in c.get("content", "")
        )
    ]
    assert len(md_cards) == 1
    content = md_cards[0]["content"]
    # Key sections must be present (FR ↔ EN equivalents).
    for fr, en in (
        ("Géométrie du soleil", "Sun geometry"),
        ("Luminosité (gate adaptatif)", "Lux (adaptive gate)"),
        ("UV (gate optionnel)", "UV (optional gate)"),
        ("Températures", "Temperatures"),
        ("Hystérésis et debounce", "Hysteresis and debounce"),
        ("Configuration de la sous-entrée", "Subentry configuration"),
        ("Décision finale", "Final decision"),
    ):
        assert fr in content or en in content, (
            f"missing section: {fr} / {en}"
        )
    # Live templates reference the per-subentry sensors.
    assert "states('sensor.salon_sud_sun_protection_status')" in content
    assert "states('sensor.salon_sud_sun_protection_lux')" in content
    assert "states('binary_sensor.salon_sud_sun_protection_active')" in content
    # Static thresholds and the subentry's own config land in the table.
    assert "10 min" in content  # close debounce
    assert "20 min" in content  # open debounce
    assert "≤ 60°" in content   # DEFAULT_ARC value


async def test_scheduler_view_header_links_back_to_cockpit(
    hass: HomeAssistant,
) -> None:
    """The first card is a compact markdown header with a back link."""
    entry = _hub_with_subentries(subentries=[_schedule_sub("Bureau", "bureau")])
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    bureau = next(v for v in config["views"] if v["path"] == "bureau")
    header = bureau["cards"][0]
    assert header["type"] == "markdown"
    assert f"(/{PANEL_URL_PATH}/cockpit)" in header["content"]
    assert "Bureau" in header["content"]


# ---------------------------------------------------------------------------
# Registration lifecycle
# ---------------------------------------------------------------------------


async def test_panel_registered_on_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Setup must register both the sidebar panel and the Lovelace dashboard."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    panels = hass.data.get(frontend.DATA_PANELS, {})
    assert PANEL_URL_PATH in panels
    panel = panels[PANEL_URL_PATH]
    assert panel.sidebar_title == PANEL_TITLE
    assert panel.sidebar_icon == PANEL_ICON
    assert panel.component_name == "lovelace"
    # The frontend panel only carries the mode marker; the dashboard
    # YAML lives in lovelace's dashboards dict.
    assert panel.config == {"mode": "yaml"}

    dashboard = hass.data["lovelace"].dashboards[PANEL_URL_PATH]
    loaded = await dashboard.async_load(False)
    assert loaded["title"] == PANEL_TITLE
    assert any(v["path"] == "cockpit" for v in loaded["views"])


async def test_panel_unregistered_on_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Unloading must remove both the sidebar panel and the dashboard."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[frontend.DATA_PANELS]
    assert PANEL_URL_PATH in hass.data["lovelace"].dashboards

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data.get(frontend.DATA_PANELS, {})
    assert PANEL_URL_PATH not in hass.data["lovelace"].dashboards


def test_view_path_uses_subentry_unique_id_slug() -> None:
    """The per-subentry view path matches the entity_id prefix."""

    class _Sub:
        unique_id = "salon_sud"
        title = "Salon Sud"

    assert _view_path(_Sub()) == "salon_sud"
