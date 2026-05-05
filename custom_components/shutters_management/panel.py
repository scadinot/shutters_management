"""Lovelace sidebar panel for the Shutters Management integration.

The panel is a Lovelace YAML dashboard registered on the sidebar via
``frontend.async_register_built_in_panel``. It contains:

* a *cockpit* view listing every subentry by type with quick-access
  tiles that navigate to per-subentry drill-down views;
* one drill-down view per schedule / presence-simulation subentry,
  showing the next-trigger sensors, controlled covers and test
  buttons;
* one drill-down view per sun-protection subentry, showing the
  configured arc as an inline-SVG sun map (with the live sun position
  rendered through Jinja templates), four gauges for the operational
  margins and a one-hour history graph for lux + indoor temperature.

The dashboard is rebuilt on subentry add / remove via the existing
update listener in ``__init__.py``: a reload of the hub entry calls
``async_unregister_panel`` then ``async_register_panel`` with the
fresh subentry list. Hub-only changes that do not trigger a reload
fall back to a direct re-register.
"""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import (
    CONF_ARC,
    CONF_COVERS,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_ORIENTATION,
    CONF_PRESENCE_ENTITY,
    CONF_TARGET_POSITION,
    CONF_TEMP_INDOOR_ENTITY,
    DEFAULT_ARC,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    DEFAULT_TARGET_POSITION,
    DOMAIN,
    HUB_TITLE,
    LUX_STANDARD,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
)


PANEL_URL_PATH = "shutters-management"
# Reuse HUB_TITLE so the sidebar entry and the hub device share a single
# source of truth. The title is the integration's brand name and is left
# untranslated on purpose; only the view labels are localized via _labels().
PANEL_TITLE = HUB_TITLE
PANEL_ICON = "mdi:blinds"


_LABELS_FR: dict[str, str] = {
    "cockpit": "Cockpit",
    "back_to_cockpit": "Retour au cockpit",
    "schedules": "Planifications",
    "simulations": "Simulations de présence",
    "sun_protections": "Protections solaires",
    "household_presence": "Présence du foyer",
    "pause_all": "Tout en pause",
    "resume_all": "Tout reprendre",
    "next_open": "Prochaine ouverture",
    "next_close": "Prochaine fermeture",
    "covers": "Volets pilotés",
    "test_open": "Tester l'ouverture",
    "test_close": "Tester la fermeture",
    "sun_map": "Carte du soleil",
    "margins": "Marges",
    "history": "Évolution dernière heure",
    "configuration": "Configuration",
    "no_subentries": (
        "Aucune sous-entrée n'est configurée. Ajoutez une planification, "
        "une simulation de présence ou une protection solaire depuis "
        "l'intégration."
    ),
    "lux_margin": "Marge lux",
    "elevation_margin": "Marge élévation",
    "uv_margin": "Marge UV",
    "azimuth_diff": "Écart d'azimuth",
    "status": "Statut",
    "override": "Override",
    "orientation": "Orientation",
    "arc": "Arc",
    "target_position": "Position cible",
    "active": "Activée",
    "view_overview": "Vue d'ensemble des éléments configurés.",
}

_LABELS_EN: dict[str, str] = {
    "cockpit": "Cockpit",
    "back_to_cockpit": "Back to cockpit",
    "schedules": "Schedules",
    "simulations": "Presence simulations",
    "sun_protections": "Sun protections",
    "household_presence": "Household presence",
    "pause_all": "Pause all",
    "resume_all": "Resume all",
    "next_open": "Next open",
    "next_close": "Next close",
    "covers": "Controlled covers",
    "test_open": "Test open",
    "test_close": "Test close",
    "sun_map": "Sun map",
    "margins": "Margins",
    "history": "Last hour",
    "configuration": "Configuration",
    "no_subentries": (
        "No sub-entry is configured. Add a schedule, presence simulation "
        "or sun protection from the integration."
    ),
    "lux_margin": "Lux margin",
    "elevation_margin": "Elevation margin",
    "uv_margin": "UV margin",
    "azimuth_diff": "Azimuth diff",
    "status": "Status",
    "override": "Override",
    "orientation": "Orientation",
    "arc": "Arc",
    "target_position": "Target position",
    "active": "Active",
    "view_overview": "Overview of every configured element.",
}


def _labels(hass: HomeAssistant) -> dict[str, str]:
    """Return French labels when HA is in French, English otherwise."""
    language = (hass.config.language or "en").lower()
    return _LABELS_FR if language.startswith("fr") else _LABELS_EN


# ---------------------------------------------------------------------------
# Entity-id and navigation helpers
# ---------------------------------------------------------------------------


def _entity_prefix(subentry: ConfigSubentry) -> str:
    """Slug used by ``entities._build_entity_id`` to derive entity_ids."""
    return subentry.unique_id or slugify(subentry.title)


def _view_path(subentry: ConfigSubentry) -> str:
    """URL-safe slug for the per-subentry drill-down view."""
    return slugify(_entity_prefix(subentry))


def _navigate_to(view_path: str) -> dict[str, str]:
    return {
        "action": "navigate",
        "navigation_path": f"/{PANEL_URL_PATH}/{view_path}",
    }


def _back_button(label: str) -> dict[str, Any]:
    return {
        "type": "button",
        "name": label,
        "icon": "mdi:arrow-left",
        "tap_action": _navigate_to("cockpit"),
        "show_state": False,
    }


# ---------------------------------------------------------------------------
# Sun map SVG helpers
# ---------------------------------------------------------------------------


def _arc_path(
    orientation_deg: float,
    arc_deg: float,
    cx: int = 100,
    cy: int = 100,
    r: int = 85,
) -> str:
    """Return an SVG path string drawing the configured arc wedge.

    ``orientation_deg`` is a compass bearing (0=N, 90=E, ...). The
    wedge spans ``orientation_deg ± arc_deg/2`` from the centre to the
    horizon circle, suitable for an ``<svg viewBox='0 0 200 200'>``
    canvas with a horizon circle of radius ``r`` centred at
    ``(cx, cy)``.
    """
    half = arc_deg / 2
    sx = cx + r * math.sin(math.radians(orientation_deg - half))
    sy = cy - r * math.cos(math.radians(orientation_deg - half))
    ex = cx + r * math.sin(math.radians(orientation_deg + half))
    ey = cy - r * math.cos(math.radians(orientation_deg + half))
    large = 1 if arc_deg > 180 else 0
    return (
        f"M {cx} {cy} "
        f"L {sx:.2f} {sy:.2f} "
        f"A {r} {r} 0 {large} 1 {ex:.2f} {ey:.2f} Z"
    )


def _sun_map_markdown(subentry: ConfigSubentry) -> str:
    """Inline-SVG sun map with a Jinja-driven live sun marker.

    The markdown card evaluates ``{{ states(...) }}`` at every state
    change of the referenced entities, so the gold sun dot tracks the
    sun in real time without any custom card.
    """
    prefix = _entity_prefix(subentry)
    orientation = subentry.data.get(CONF_ORIENTATION, 180)
    arc = subentry.data.get(CONF_ARC, DEFAULT_ARC)
    az_entity = f"sensor.{prefix}_sun_protection_sun_azimuth"
    el_entity = f"sensor.{prefix}_sun_protection_sun_elevation"
    arc_path = _arc_path(orientation, arc)

    return (
        '<svg viewBox="0 0 200 200" '
        'style="width:100%;max-height:320px;display:block;margin:0 auto">\n'
        '  <circle cx="100" cy="100" r="85" fill="#101820" '
        'stroke="#4a4a4a" stroke-width="1"/>\n'
        '  <circle cx="100" cy="100" r="42.5" fill="none" '
        'stroke="#262626" stroke-width="0.5" stroke-dasharray="2 3"/>\n'
        f'  <path d="{arc_path}" fill="rgba(255,196,0,0.18)" '
        'stroke="rgba(255,196,0,0.7)" stroke-width="1"/>\n'
        '  <line x1="100" y1="15" x2="100" y2="185" '
        'stroke="#333" stroke-width="0.5"/>\n'
        '  <line x1="15" y1="100" x2="185" y2="100" '
        'stroke="#333" stroke-width="0.5"/>\n'
        '  <text x="100" y="12" fill="#aaa" text-anchor="middle" '
        'font-size="10">N</text>\n'
        '  <text x="192" y="104" fill="#aaa" text-anchor="middle" '
        'font-size="10">E</text>\n'
        '  <text x="100" y="198" fill="#aaa" text-anchor="middle" '
        'font-size="10">S</text>\n'
        '  <text x="8" y="104" fill="#aaa" text-anchor="middle" '
        'font-size="10">W</text>\n'
        f"  {{% set az_raw = states('{az_entity}') %}}\n"
        f"  {{% set el_raw = states('{el_entity}') %}}\n"
        "  {% if az_raw not in ['unknown','unavailable','none',None] "
        "and el_raw not in ['unknown','unavailable','none',None] %}\n"
        "  {% set az_f = az_raw | float(0) %}\n"
        "  {% set el_f = el_raw | float(-90) %}\n"
        "  {% if el_f > -5 %}\n"
        "  {% set rrad = (90 - el_f) / 90 * 85 %}\n"
        "  {% set sx = 100 + rrad * sin(radians(az_f)) %}\n"
        "  {% set sy = 100 - rrad * cos(radians(az_f)) %}\n"
        '  <circle cx="{{ "%.2f" | format(sx) }}" '
        'cy="{{ "%.2f" | format(sy) }}" r="7" fill="gold" '
        'stroke="orange" stroke-width="2"/>\n'
        "  {% endif %}\n"
        "  {% endif %}\n"
        "</svg>\n"
    )


# ---------------------------------------------------------------------------
# View builders
# ---------------------------------------------------------------------------


def _scheduler_tile(subentry: ConfigSubentry) -> dict[str, Any]:
    prefix = _entity_prefix(subentry)
    return {
        "type": "tile",
        "entity": f"switch.{prefix}_simulation_active",
        "name": subentry.title,
        "icon": (
            "mdi:account-clock"
            if subentry.subentry_type == SUBENTRY_TYPE_PRESENCE_SIM
            else "mdi:calendar-clock"
        ),
        "tap_action": _navigate_to(_view_path(subentry)),
    }


def _sun_tile(subentry: ConfigSubentry) -> dict[str, Any]:
    prefix = _entity_prefix(subentry)
    return {
        "type": "tile",
        "entity": f"binary_sensor.{prefix}_sun_protection_active",
        "name": subentry.title,
        "icon": "mdi:weather-sunny",
        "tap_action": _navigate_to(_view_path(subentry)),
    }


def _build_cockpit_view(
    hass: HomeAssistant, entry: ConfigEntry, labels: dict[str, str]
) -> dict[str, Any]:
    """Top-level cockpit listing every subentry grouped by type."""
    schedules: list[ConfigSubentry] = []
    sims: list[ConfigSubentry] = []
    suns: list[ConfigSubentry] = []
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_TYPE_INSTANCE:
            schedules.append(sub)
        elif sub.subentry_type == SUBENTRY_TYPE_PRESENCE_SIM:
            sims.append(sub)
        elif sub.subentry_type == SUBENTRY_TYPE_SUN_PROTECTION:
            suns.append(sub)

    cards: list[dict[str, Any]] = []

    cards.append(
        {
            "type": "markdown",
            "content": f"## {PANEL_TITLE}\n\n{labels['view_overview']}",
        }
    )

    presence_entities = list(entry.data.get(CONF_PRESENCE_ENTITY) or [])
    if presence_entities:
        cards.append(
            {
                "type": "entities",
                "title": labels["household_presence"],
                "entities": presence_entities,
                "show_header_toggle": False,
            }
        )

    if not (schedules or sims or suns):
        cards.append(
            {"type": "markdown", "content": labels["no_subentries"]}
        )

    if schedules:
        cards.append(
            {
                "type": "markdown",
                "content": f"### {labels['schedules']}",
            }
        )
        cards.append(
            {
                "type": "grid",
                "columns": 1,
                "square": False,
                "cards": [
                    _scheduler_tile(sub) for sub in schedules
                ],
            }
        )
    if sims:
        cards.append(
            {
                "type": "markdown",
                "content": f"### {labels['simulations']}",
            }
        )
        cards.append(
            {
                "type": "grid",
                "columns": 1,
                "square": False,
                "cards": [_scheduler_tile(sub) for sub in sims],
            }
        )
    if suns:
        cards.append(
            {
                "type": "markdown",
                "content": f"### {labels['sun_protections']}",
            }
        )
        cards.append(
            {
                "type": "grid",
                "columns": 1,
                "square": False,
                "cards": [_sun_tile(sub) for sub in suns],
            }
        )

    cards.append(
        {
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button",
                    "name": labels["pause_all"],
                    "icon": "mdi:pause",
                    "tap_action": {
                        "action": "call-service",
                        "service": f"{DOMAIN}.{SERVICE_PAUSE}",
                    },
                    "show_state": False,
                },
                {
                    "type": "button",
                    "name": labels["resume_all"],
                    "icon": "mdi:play",
                    "tap_action": {
                        "action": "call-service",
                        "service": f"{DOMAIN}.{SERVICE_RESUME}",
                    },
                    "show_state": False,
                },
            ],
        }
    )

    return {
        "title": labels["cockpit"],
        "path": "cockpit",
        "icon": "mdi:view-dashboard",
        "cards": cards,
    }


def _build_scheduler_view(
    subentry: ConfigSubentry, labels: dict[str, str]
) -> dict[str, Any]:
    """Drill-down view for a Planification or Simulation subentry."""
    prefix = _entity_prefix(subentry)
    covers = list(subentry.data.get(CONF_COVERS) or [])
    is_sim = subentry.subentry_type == SUBENTRY_TYPE_PRESENCE_SIM

    schedule_entities: list[dict[str, Any] | str] = [
        f"switch.{prefix}_simulation_active",
        {
            "entity": f"sensor.{prefix}_next_open",
            "name": labels["next_open"],
        },
        {
            "entity": f"sensor.{prefix}_next_close",
            "name": labels["next_close"],
        },
    ]

    cards: list[dict[str, Any]] = []
    cards.append(_back_button(labels["back_to_cockpit"]))
    cards.append(
        {
            "type": "markdown",
            "content": f"## {subentry.title}",
        }
    )
    cards.append(
        {
            "type": "entities",
            "title": labels["schedules"] if not is_sim else labels["simulations"],
            "show_header_toggle": False,
            "entities": schedule_entities,
        }
    )

    if covers:
        cards.append(
            {
                "type": "entities",
                "title": labels["covers"],
                "show_header_toggle": False,
                "entities": list(covers),
            }
        )

    cards.append(
        {
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button",
                    "name": labels["test_open"],
                    "icon": "mdi:arrow-up-circle-outline",
                    "tap_action": {
                        "action": "call-service",
                        "service": "button.press",
                        "target": {
                            "entity_id": f"button.{prefix}_open",
                        },
                    },
                    "show_state": False,
                },
                {
                    "type": "button",
                    "name": labels["test_close"],
                    "icon": "mdi:arrow-down-circle-outline",
                    "tap_action": {
                        "action": "call-service",
                        "service": "button.press",
                        "target": {
                            "entity_id": f"button.{prefix}_close",
                        },
                    },
                    "show_state": False,
                },
            ],
        }
    )

    return {
        "title": subentry.title,
        "path": _view_path(subentry),
        "icon": (
            "mdi:account-clock" if is_sim else "mdi:calendar-clock"
        ),
        "cards": cards,
    }


def _gauge_card(
    entity_id: str,
    name: str,
    *,
    unit: str | None = None,
    minimum: float = -100,
    maximum: float = 100,
    severity: dict[str, float] | None = None,
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "type": "gauge",
        "entity": entity_id,
        "name": name,
        "min": minimum,
        "max": maximum,
        "needle": True,
    }
    if unit is not None:
        card["unit"] = unit
    if severity is not None:
        card["severity"] = severity
    return card


def _build_sun_protection_view(
    subentry: ConfigSubentry, labels: dict[str, str]
) -> dict[str, Any]:
    """Drill-down view for a sun-protection subentry (graphical)."""
    prefix = _entity_prefix(subentry)
    covers = list(subentry.data.get(CONF_COVERS) or [])
    arc = subentry.data.get(CONF_ARC, DEFAULT_ARC)
    min_elevation = subentry.data.get(
        CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION
    )
    target_position = subentry.data.get(
        CONF_TARGET_POSITION, DEFAULT_TARGET_POSITION
    )
    orientation = subentry.data.get(CONF_ORIENTATION, 180)
    min_uv = subentry.data.get(CONF_MIN_UV, DEFAULT_MIN_UV)

    cards: list[dict[str, Any]] = []
    cards.append(_back_button(labels["back_to_cockpit"]))
    cards.append(
        {
            "type": "markdown",
            "content": f"## {subentry.title}",
        }
    )
    cards.append(
        {
            "type": "entities",
            "show_header_toggle": False,
            "entities": [
                f"switch.{prefix}_sun_protection",
                {
                    "entity": f"binary_sensor.{prefix}_sun_protection_active",
                    "name": labels["active"],
                },
                {
                    "entity": f"sensor.{prefix}_sun_protection_status",
                    "name": labels["status"],
                },
                {
                    "entity": f"sensor.{prefix}_sun_protection_override_until",
                    "name": labels["override"],
                },
            ],
        }
    )

    # Sun map
    cards.append(
        {
            "type": "markdown",
            "title": labels["sun_map"],
            "content": _sun_map_markdown(subentry),
        }
    )

    # Margins gauges
    cards.append(
        {
            "type": "markdown",
            "content": f"### {labels['margins']}",
        }
    )
    gauges: list[dict[str, Any]] = []
    gauges.append(
        _gauge_card(
            f"sensor.{prefix}_sun_protection_lux_margin",
            labels["lux_margin"],
            unit="lx",
            minimum=-LUX_STANDARD,
            maximum=LUX_STANDARD,
            severity={"green": 0, "yellow": -10000, "red": -25000},
        )
    )
    gauges.append(
        _gauge_card(
            f"sensor.{prefix}_sun_protection_elevation_margin",
            labels["elevation_margin"],
            unit="°",
            minimum=-float(min_elevation),
            maximum=90 - float(min_elevation),
            severity={"green": 0, "yellow": -3, "red": -10},
        )
    )
    gauges.append(
        _gauge_card(
            f"sensor.{prefix}_sun_protection_uv_margin",
            labels["uv_margin"],
            unit="",
            minimum=-float(min_uv),
            maximum=10 - float(min_uv),
            severity={"green": 0, "yellow": -1, "red": -2},
        )
    )
    gauges.append(
        _gauge_card(
            f"sensor.{prefix}_sun_protection_azimuth_diff",
            labels["azimuth_diff"],
            unit="°",
            minimum=0,
            maximum=180,
            severity={"green": 0, "yellow": float(arc), "red": float(arc) + 15},
        )
    )
    cards.append(
        {
            "type": "grid",
            "columns": 2,
            "square": True,
            "cards": gauges,
        }
    )

    # History graph: lux + indoor temperature over the last hour.
    history_entities: list[str] = [
        f"sensor.{prefix}_sun_protection_lux",
    ]
    if subentry.data.get(CONF_TEMP_INDOOR_ENTITY):
        history_entities.append(
            f"sensor.{prefix}_sun_protection_temp_indoor"
        )
    cards.append(
        {
            "type": "history-graph",
            "title": labels["history"],
            "hours_to_show": 1,
            "entities": history_entities,
        }
    )

    # Configuration recap
    config_entities: list[Any] = [
        {
            "type": "section",
            "label": labels["configuration"],
        },
    ]
    config_entities.extend(
        [
            {
                "type": "attribute",
                "entity": f"binary_sensor.{prefix}_sun_protection_active",
                "attribute": "orientation",
                "name": labels["orientation"],
            },
            {
                "type": "attribute",
                "entity": f"binary_sensor.{prefix}_sun_protection_active",
                "attribute": "arc",
                "name": labels["arc"],
                "suffix": "°",
            },
        ]
    )
    cards.append(
        {
            "type": "entities",
            "show_header_toggle": False,
            "entities": config_entities,
        }
    )
    if covers:
        cards.append(
            {
                "type": "entities",
                "title": (
                    f"{labels['covers']} — {labels['target_position']} "
                    f"{target_position}%"
                ),
                "show_header_toggle": False,
                "entities": list(covers),
            }
        )

    return {
        "title": subentry.title,
        "path": _view_path(subentry),
        "icon": "mdi:weather-sunny",
        "cards": cards,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_dashboard_config(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return the full Lovelace dashboard config for the panel.

    Layout: a cockpit view first, then one drill-down view per subentry
    (schedule, presence simulation, or sun protection). Subentry views
    are ordered to match the cockpit groups for consistency.
    """
    labels = _labels(hass)

    schedules: list[ConfigSubentry] = []
    sims: list[ConfigSubentry] = []
    suns: list[ConfigSubentry] = []
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_TYPE_INSTANCE:
            schedules.append(sub)
        elif sub.subentry_type == SUBENTRY_TYPE_PRESENCE_SIM:
            sims.append(sub)
        elif sub.subentry_type == SUBENTRY_TYPE_SUN_PROTECTION:
            suns.append(sub)

    views: list[dict[str, Any]] = [_build_cockpit_view(hass, entry, labels)]
    for sub in schedules:
        views.append(_build_scheduler_view(sub, labels))
    for sub in sims:
        views.append(_build_scheduler_view(sub, labels))
    for sub in suns:
        views.append(_build_sun_protection_view(sub, labels))

    return {"title": PANEL_TITLE, "views": views}


def async_register_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register (or refresh) the sidebar panel for the hub entry.

    Idempotent: any previous registration is removed first so the call
    is safe to issue from both initial setup and an update listener
    that fires without a full reload.
    """
    dashboard = build_dashboard_config(hass, entry)
    frontend.async_remove_panel(
        hass, PANEL_URL_PATH, warn_if_unknown=False
    )
    frontend.async_register_built_in_panel(
        hass,
        component_name="lovelace",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        config={"mode": "yaml", "config": dashboard},
        require_admin=False,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel if registered."""
    frontend.async_remove_panel(
        hass, PANEL_URL_PATH, warn_if_unknown=False
    )
