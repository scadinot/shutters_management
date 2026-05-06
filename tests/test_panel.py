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
    _arc_data_uri,
    _arc_path,
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


def test_arc_data_uri_starts_with_data_image_svg() -> None:
    """``_arc_data_uri`` returns a URL-encoded inline SVG image."""
    uri = _arc_data_uri(180, 60)
    assert uri.startswith("data:image/svg+xml;utf8,")
    # The SVG body itself is URL-encoded; decode and verify the arc path
    # is present.
    from urllib.parse import unquote

    decoded = unquote(uri.split(",", 1)[1])
    assert decoded.startswith("<svg")
    assert decoded.endswith("</svg>")
    assert "M 100 100 L " in decoded
    assert " A 85 85 0 0 1 " in decoded


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


async def test_sun_protection_view_has_sun_map_and_gauges(
    hass: HomeAssistant,
) -> None:
    """The drill-down view embeds the arc as a picture card + gauges."""
    entry = _hub_with_subentries(
        subentries=[_sun_sub("Salon Sud", "salon_sud")]
    )
    entry.add_to_hass(hass)

    config = build_dashboard_config(hass, entry)
    sun_view = next(v for v in config["views"] if v["path"] == "salon_sud")

    # Sun map is now a picture card with a data:image/svg+xml URI;
    # the inline-SVG-in-markdown approach was stripped by HA's
    # markdown sanitizer.
    pictures = [c for c in sun_view["cards"] if c["type"] == "picture"]
    assert pictures, "expected a picture card for the sun map"
    assert pictures[0]["image"].startswith("data:image/svg+xml;utf8,")

    # Four gauges (with lux + UV configured in _hub_with_subentries).
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

    gauges = [
        card
        for c in sun_view["cards"]
        if c["type"] == "grid"
        for card in c.get("cards", [])
        if card.get("type") == "gauge"
    ]
    gauge_entities = {g["entity"] for g in gauges}
    assert gauge_entities == {
        "sensor.salon_sud_sun_protection_elevation_margin",
        "sensor.salon_sud_sun_protection_azimuth_diff",
    }
    # Without a lux series (and no temp_indoor in this fixture), the
    # history-graph card is omitted entirely.
    assert not any(
        c["type"] == "history-graph" for c in sun_view["cards"]
    )


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
