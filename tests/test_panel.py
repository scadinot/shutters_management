"""Tests for the Lovelace sidebar panel built by ``panel.py``."""
from __future__ import annotations

import math
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
    _arc_path,
    _sun_map_markdown,
    _view_path,
    build_dashboard_config,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_arc_path_south_60_deg() -> None:
    """South façade with a 60° arc: the wedge is centred on (cx, cy+r)."""
    path = _arc_path(180, 60)
    # Centre move + line to start point + arc to end + close.
    assert path.startswith("M 100 100 L ")
    assert " A 85 85 0 0 1 " in path
    assert path.endswith(" Z")
    # The two endpoint coordinates straddle the south meridian: at
    # ±30° around south (180°) the y-component is cy − r·cos(±150°) =
    # 100 + 85·(√3/2) ≈ 173.6, and the x-component is ±85·sin(±150°)
    # = ∓42.5, i.e. (57.5, 173.6) and (142.5, 173.6).
    pieces = path.split()
    sx, sy = float(pieces[4]), float(pieces[5])
    ex, ey = float(pieces[-3]), float(pieces[-2])
    # Start at compass 150°, end at 210°: x = 100 + 85·sin(bearing),
    # y = 100 − 85·cos(bearing). Both endpoints share the same y at
    # the same |bearing − 180°|; their x's are mirrored across the
    # south meridian.
    assert math.isclose(sx, 100 + 85 * math.sin(math.radians(150)), abs_tol=0.05)
    assert math.isclose(sy, 100 - 85 * math.cos(math.radians(150)), abs_tol=0.05)
    assert math.isclose(ex, 100 + 85 * math.sin(math.radians(210)), abs_tol=0.05)
    assert math.isclose(ey, 100 - 85 * math.cos(math.radians(210)), abs_tol=0.05)


def test_arc_path_large_arc_flag() -> None:
    """An arc wider than 180° must set the large-arc flag."""
    path = _arc_path(0, 270)
    assert " A 85 85 0 1 1 " in path


def test_sun_map_markdown_references_subentry_sensors() -> None:
    """The SVG template must reference the per-subentry azimuth/elevation sensors."""
    sub = ConfigSubentryData(
        subentry_type=SUBENTRY_TYPE_SUN_PROTECTION,
        title="Salon Sud",
        unique_id="salon_sud",
        data={CONF_ORIENTATION: 180, CONF_ARC: 60},
    )
    # Build a faux ConfigSubentry-like wrapper since ``_sun_map_markdown``
    # only reads ``unique_id``, ``title`` and ``data`` attributes.
    class _Sub:
        unique_id = sub["unique_id"]
        title = sub["title"]
        data = sub["data"]

    md = _sun_map_markdown(_Sub())
    assert "sensor.salon_sud_sun_protection_sun_azimuth" in md
    assert "sensor.salon_sud_sun_protection_sun_elevation" in md
    assert "<svg " in md and "</svg>" in md
    assert "sin(radians(az_f))" in md
    assert "cos(radians(az_f))" in md


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


async def test_sun_protection_view_has_sun_map_and_gauges(
    hass: HomeAssistant,
) -> None:
    """A sun-protection drill-down view embeds the SVG arc and the gauges."""
    entry = _hub_with_subentries(
        subentries=[_sun_sub("Salon Sud", "salon_sud")]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    sun_view = next(v for v in config["views"] if v["path"] == "salon_sud")

    card_types = [c["type"] for c in sun_view["cards"]]
    assert "history-graph" in card_types
    # Sun map is a markdown card containing inline SVG.
    md_with_svg = [
        c
        for c in sun_view["cards"]
        if c["type"] == "markdown" and "<svg " in c.get("content", "")
    ]
    assert md_with_svg, "expected at least one markdown card with inline SVG"
    # Four gauges under a grid: lux / elevation / uv / azimuth_diff margins.
    grids = [c for c in sun_view["cards"] if c["type"] == "grid"]
    assert grids, "expected a grid containing the margin gauges"
    gauges = [
        card
        for grid in grids
        for card in grid.get("cards", [])
        if card.get("type") == "gauge"
    ]
    gauge_entities = {g["entity"] for g in gauges}
    assert gauge_entities == {
        "sensor.salon_sud_sun_protection_lux_margin",
        "sensor.salon_sud_sun_protection_elevation_margin",
        "sensor.salon_sud_sun_protection_uv_margin",
        "sensor.salon_sud_sun_protection_azimuth_diff",
    }


async def test_scheduler_view_links_back_to_cockpit(
    hass: HomeAssistant,
) -> None:
    """Each drill-down view starts with a back-button to /cockpit."""
    entry = _hub_with_subentries(subentries=[_schedule_sub("Bureau", "bureau")])
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    bureau = next(v for v in config["views"] if v["path"] == "bureau")
    assert bureau["cards"][0]["type"] == "button"
    nav = bureau["cards"][0]["tap_action"]
    assert nav["action"] == "navigate"
    assert nav["navigation_path"] == f"/{PANEL_URL_PATH}/cockpit"


# ---------------------------------------------------------------------------
# Registration lifecycle
# ---------------------------------------------------------------------------


async def test_panel_registered_on_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Setting up the hub entry registers the sidebar panel."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    panels = hass.data.get(frontend.DATA_PANELS, {})
    assert PANEL_URL_PATH in panels
    panel = panels[PANEL_URL_PATH]
    assert panel.sidebar_title == PANEL_TITLE
    assert panel.sidebar_icon == PANEL_ICON
    assert panel.component_name == "lovelace"
    config = panel.config
    assert config["mode"] == "yaml"
    assert config["config"]["title"] == PANEL_TITLE
    assert any(
        v["path"] == "cockpit" for v in config["config"]["views"]
    )


async def test_panel_unregistered_on_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Unloading the hub entry removes the panel."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[frontend.DATA_PANELS]

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data.get(frontend.DATA_PANELS, {})


def test_view_path_uses_subentry_unique_id_slug() -> None:
    """The per-subentry view path matches the entity_id prefix."""

    class _Sub:
        unique_id = "salon_sud"
        title = "Salon Sud"

    assert _view_path(_Sub()) == "salon_sud"
