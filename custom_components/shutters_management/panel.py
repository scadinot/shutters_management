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

import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import MODE_YAML
from homeassistant.components.lovelace.dashboard import LovelaceConfig
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.json import json_bytes, json_fragment
from homeassistant.util import slugify

from .const import (
    CONF_ARC,
    CONF_COVERS,
    CONF_LUX_ENTITY,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_ORIENTATION,
    CONF_PRESENCE_ENTITY,
    CONF_TARGET_POSITION,
    CONF_TEMP_INDOOR_ENTITY,
    CONF_UV_ENTITY,
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
    "sun_position": "Position du soleil",
    "trigger": "Lancer",
    "azimuth": "Azimuth",
    "elevation": "Élévation",
    "sun_facing": "Soleil face à la façade",
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
    "sun_position": "Sun position",
    "trigger": "Trigger",
    "azimuth": "Azimuth",
    "elevation": "Elevation",
    "sun_facing": "Sun facing the façade",
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


def _header_card(title: str, labels: dict[str, str]) -> dict[str, Any]:
    """Compact view header: a markdown link back to the cockpit + the title.

    Replaces the legacy big-button card. The link is a same-origin HA
    route (``/shutters-management/cockpit``); the frontend intercepts
    such internal links in markdown and routes them as in-app
    navigation, so the click does not reload the page.
    """
    nav_path = f"/{PANEL_URL_PATH}/cockpit"
    return {
        "type": "markdown",
        "content": (
            f"[← {labels['back_to_cockpit']}]({nav_path})\n\n"
            f"## {title}"
        ),
    }


def _action_button_row(
    name: str,
    icon: str,
    target_entity_id: str,
    action_label: str,
) -> dict[str, Any]:
    """Compact ``entities``-card row that calls ``button.press`` on click."""
    return {
        "type": "button",
        "name": name,
        "icon": icon,
        "action_name": action_label,
        "tap_action": {
            "action": "call-service",
            "service": "button.press",
            "target": {"entity_id": target_entity_id},
        },
    }


def _service_button_row(
    name: str,
    icon: str,
    service: str,
    action_label: str,
) -> dict[str, Any]:
    """Compact ``entities``-card row that calls ``service`` on click."""
    return {
        "type": "button",
        "name": name,
        "icon": icon,
        "action_name": action_label,
        "tap_action": {
            "action": "call-service",
            "service": service,
        },
    }


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
            "type": "entities",
            "show_header_toggle": False,
            "entities": [
                _service_button_row(
                    labels["pause_all"],
                    "mdi:pause",
                    f"{DOMAIN}.{SERVICE_PAUSE}",
                    labels["trigger"],
                ),
                _service_button_row(
                    labels["resume_all"],
                    "mdi:play",
                    f"{DOMAIN}.{SERVICE_RESUME}",
                    labels["trigger"],
                ),
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
    cards.append(_header_card(subentry.title, labels))
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
            "type": "entities",
            "show_header_toggle": False,
            "entities": [
                _action_button_row(
                    labels["test_open"],
                    "mdi:arrow-up-circle-outline",
                    f"button.{prefix}_open",
                    labels["trigger"],
                ),
                _action_button_row(
                    labels["test_close"],
                    "mdi:arrow-down-circle-outline",
                    f"button.{prefix}_close",
                    labels["trigger"],
                ),
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


def _conditional_numeric_card(card: dict[str, Any]) -> dict[str, Any]:
    """Hide ``card`` when its entity is ``unknown`` or ``unavailable``.

    The sun-protection margin sensors return ``None`` when the
    relevant input is missing (e.g. lux_margin is ``None`` while
    ``t_ext < T_OUTDOOR_NO_PROTECT`` because the integration won't
    protect in cold weather). HA exposes that as ``unknown`` and a
    bare ``gauge`` card renders the warning « L'entité n'est pas
    numérique ». Wrap each numeric card in a ``conditional`` so it
    disappears cleanly instead.
    """
    entity = card["entity"]
    return {
        "type": "conditional",
        "conditions": [
            {"entity": entity, "state_not": "unknown"},
            {"entity": entity, "state_not": "unavailable"},
        ],
        "card": card,
    }


def _build_sun_protection_view(
    hass: HomeAssistant,
    hub_entry: ConfigEntry,
    subentry: ConfigSubentry,
    labels: dict[str, str],
) -> dict[str, Any]:
    """Drill-down view for a sun-protection subentry (graphical).

    Adapts to the hub configuration: gauges and history series that
    require a sensor not provided by the hub (lux / UV) are skipped to
    avoid the « entity is not numeric » warning that surfaces when the
    underlying margin sensor is ``None``.
    """
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

    has_lux = bool(hub_entry.data.get(CONF_LUX_ENTITY))
    has_uv = bool(hub_entry.data.get(CONF_UV_ENTITY))
    has_temp_indoor = bool(subentry.data.get(CONF_TEMP_INDOOR_ENTITY))

    cards: list[dict[str, Any]] = []
    cards.append(_header_card(subentry.title, labels))
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

    # 3D sun + window scene served by the custom card registered via
    # add_extra_js_url in __init__.py. The card receives `hass` from
    # the Lovelace runtime and reads `sun.sun.attributes.azimuth /
    # elevation` directly — no token, no REST round-trip.
    cards.append(
        {
            "type": "custom:shutters-sun-3d-card",
            "subentry_prefix": prefix,
            "orientation": orientation,
            "arc": arc,
            "min_elevation": min_elevation,
            "latitude": hass.config.latitude,
            "longitude": hass.config.longitude,
            "covers": list(covers),
        }
    )

    # Margins gauges — only those whose underlying sensor is numeric.
    # Wrap the section title and the gauges row in a vertical-stack so
    # the title cannot end up orphaned in a different column from the
    # gauges. ``horizontal-stack`` lays the gauges out in a single
    # row regardless of count (2, 3 or 4 depending on configured
    # sensors), which avoids the lop-sided 2x2 layout we saw in v0.8.2.
    gauges: list[dict[str, Any]] = []
    if has_lux:
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
    if has_uv:
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
            "type": "vertical-stack",
            "cards": [
                {
                    "type": "markdown",
                    "content": f"### {labels['margins']}",
                },
                {
                    "type": "horizontal-stack",
                    "cards": [
                        _conditional_numeric_card(g) for g in gauges
                    ],
                },
            ],
        }
    )

    # History graph: only the series whose source is configured. Skip
    # the card entirely when no series is available.
    history_entities: list[str] = []
    if has_lux:
        history_entities.append(f"sensor.{prefix}_sun_protection_lux")
    if has_temp_indoor:
        history_entities.append(
            f"sensor.{prefix}_sun_protection_temp_indoor"
        )
    if history_entities:
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
        views.append(_build_sun_protection_view(hass, entry, sub, labels))

    return {"title": PANEL_TITLE, "views": views}


_LOGGER = logging.getLogger(__name__)
_LOVELACE_DOMAIN = "lovelace"

# Subentry types that yield a drill-down view in the dashboard.
_VIEW_SUBENTRY_TYPES = (
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
)


def _expected_view_count(entry: ConfigEntry) -> int:
    """Cockpit + one drill-down view per supported subentry."""
    return 1 + sum(
        1
        for sub in entry.subentries.values()
        if sub.subentry_type in _VIEW_SUBENTRY_TYPES
    )


class _GeneratedDashboard(LovelaceConfig):
    """In-memory Lovelace dashboard rebuilt from the hub entry on demand.

    The frontend's ``<ha-panel-lovelace>`` web component fetches the
    actual dashboard YAML through a websocket call which dispatches to
    ``hass.data['lovelace'].dashboards[url_path].async_load(...)``.
    Registering only the sidebar panel without populating this dict
    leaves the panel page blank — hence this thin ``LovelaceConfig``
    subclass that returns the freshly built config on every call.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, PANEL_URL_PATH, None)
        self._entry = entry

    @property
    def mode(self) -> str:
        return MODE_YAML

    async def async_get_info(self) -> dict[str, Any]:
        # Counted from the entry's subentries directly: rebuilding the
        # full dashboard (cards, inline SVG, ...) just to count views
        # would be wasteful and HA may call this often.
        return {"mode": self.mode, "views": _expected_view_count(self._entry)}

    async def async_load(self, force: bool) -> dict[str, Any]:
        return build_dashboard_config(self.hass, self._entry)

    async def async_json(self, force: bool) -> json_fragment:
        config = await self.async_load(force)
        return json_fragment(json_bytes(config))

    @callback
    def update_entry(self, entry: ConfigEntry) -> None:
        """Re-bind the dashboard to ``entry`` and notify the frontend."""
        self._entry = entry
        self._config_updated()


def async_register_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register (or refresh) the sidebar panel for the hub entry.

    Idempotent: any previous registration is removed first so the call
    is safe to issue from both initial setup and an update listener
    that fires without a full reload.

    Two pieces are wired up: the sidebar entry (via
    ``frontend.async_register_built_in_panel``) and the actual Lovelace
    dashboard (registered in the ``lovelace`` domain's dashboards
    dict). The frontend would otherwise display an empty page.
    """
    lovelace_data = hass.data.get(_LOVELACE_DOMAIN)
    if lovelace_data is None:
        # Lovelace is set up at HA bootstrap and is also declared as a
        # manifest dependency; missing here means a misconfigured test
        # harness or a bootstrap error. Tear down any stale sidebar
        # entry so we don't leave a broken icon pointing at nothing,
        # then warn the user.
        frontend.async_remove_panel(
            hass, PANEL_URL_PATH, warn_if_unknown=False
        )
        _LOGGER.warning(
            "Cannot register %s panel: lovelace data not available",
            PANEL_URL_PATH,
        )
        return

    existing = lovelace_data.dashboards.get(PANEL_URL_PATH)
    if isinstance(existing, _GeneratedDashboard):
        existing.update_entry(entry)
    else:
        lovelace_data.dashboards[PANEL_URL_PATH] = _GeneratedDashboard(
            hass, entry
        )

    frontend.async_remove_panel(
        hass, PANEL_URL_PATH, warn_if_unknown=False
    )
    frontend.async_register_built_in_panel(
        hass,
        component_name="lovelace",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        config={"mode": MODE_YAML},
        require_admin=False,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel and the in-memory dashboard."""
    frontend.async_remove_panel(
        hass, PANEL_URL_PATH, warn_if_unknown=False
    )
    lovelace_data = hass.data.get(_LOVELACE_DOMAIN)
    if lovelace_data is not None:
        lovelace_data.dashboards.pop(PANEL_URL_PATH, None)
