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
    ARC_HYSTERESIS_DEG,
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
    DEFAULT_ORIENTATION,
    DEFAULT_TARGET_POSITION,
    DOMAIN,
    ELEVATION_HYSTERESIS_DEG,
    HUB_TITLE,
    LUX_MILD,
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
    "lux_margin": "Lux",
    "elevation_margin": "Élévation",
    "uv_margin": "UV",
    "azimuth_diff": "Azimut",
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
    "lux_short": "Lux",
    "sun_facing_short": "Face",
    "elevation_short": "Élév.",
    "all_covers": "Volets configurés",
    # « Paramètres de décision » — refonte v0.9.10 : terminologie
    # 100 % française, statut au sommet, pipeline narratif.
    "decision_state": "État de la décision",
    "current_status": "Statut courant",
    "protection_active": "Protection active",
    "manual_override": "Override manuel",
    "override_reset_note": (
        "réinitialisé automatiquement à 04 h"
    ),
    "close_conditions": "Conditions de fermeture",
    "close_conditions_intro": (
        "Toutes les conditions ci-dessous doivent être satisfaites "
        "pour que le moteur déclenche la fermeture."
    ),
    "sun_position_section": "Position du soleil",
    "sun_position_intro": (
        "Le soleil doit être suffisamment haut et dans l'arc "
        "d'acceptation de la façade."
    ),
    "outdoor_temp_section": "Température extérieure",
    "outdoor_temp_intro": (
        "La protection ne se déclenche qu'au-dessus d'un seuil de "
        "chaleur extérieure, pour préserver le gain solaire en "
        "saison fraîche."
    ),
    "lux_section": "Luminosité",
    "lux_intro": (
        "Le seuil de luminosité dépend du régime thermique extérieur "
        "(plus il fait chaud, moins il faut de soleil pour fermer)."
    ),
    "uv_section": "Indice UV (optionnel)",
    "uv_intro": (
        "Filtre supplémentaire désactivé si aucun capteur UV n'est "
        "configuré sur le hub."
    ),
    "comfort_section": "Confort intérieur (optionnel)",
    "comfort_intro": (
        "La pièce doit déjà être tiède pour justifier la fermeture "
        "— évite de fermer une pièce trop fraîche le matin."
    ),
    "timing_section": "Temporisation",
    "timing_intro": (
        "Les conditions doivent tenir un certain temps avant que le "
        "moteur n'agisse, pour éviter de réagir à un nuage de "
        "passage. Le compteur ci-dessous reflète la phase "
        "actuellement en cours (fermeture ou réouverture)."
    ),
    "config_section": "Configuration de la sous-entrée",
    "config_intro": (
        "Valeurs statiques fixées au moment de la création ou de la "
        "modification du groupe."
    ),
    # Colonnes / cellules
    "criterion": "Critère",
    "current_value": "Valeur actuelle",
    "condition": "Condition",
    "indicator": "Indicateur",
    "value": "Valeur",
    "step": "Étape",
    "duration": "Durée",
    "current_counter": "Compteur courant",
    "parameter": "Paramètre",
    # Lignes de tables (critères)
    "elevation_label": "Élévation",
    "elevation_condition": (
        "≥ {min}° (sortie à {exit}°, hystérésis −{hys}°)"
    ),
    "azimuth_diff_label": "Écart à la façade",
    "azimuth_diff_condition": (
        "≤ {arc}° (sortie à {exit}°, hystérésis +{hys}°)"
    ),
    "outdoor_temp_label": "T° extérieure",
    "outdoor_temp_condition": "≥ 20 °C pour activer la protection",
    "thermal_regime_label": "Régime adaptatif",
    "thermal_regime_value": "dépend de la T° extérieure",
    "thermal_regime_condition": (
        "mi-saison (20–24 °C) · chaud (24–30 °C) · "
        "canicule (≥ 30 °C)"
    ),
    "outdoor_lux_label": "Luminosité extérieure",
    "outdoor_lux_condition": "≥ {threshold_template} lx",
    "lux_threshold_label": "Seuil adaptatif",
    "lux_threshold_value": "dépend de la T° extérieure",
    "lux_threshold_condition": (
        "mi-saison : 70 000 lx · chaud : 50 000 lx · "
        "canicule : 35 000 lx"
    ),
    "lux_reopen_label": "Réouverture",
    "lux_reopen_condition": (
        "redescend sous 25 000 lx pendant 20 min"
    ),
    "uv_index_label": "Indice UV",
    "uv_index_condition": "≥ {min} (seuil configuré)",
    "indoor_temp_label": "T° intérieure",
    "indoor_temp_condition": (
        "≥ 23 °C en régime chaud / 24 °C en mi-saison"
    ),
    "heatwave_bypass_label": "Régime canicule",
    "heatwave_bypass_value": "T°ext ≥ 30 °C",
    "heatwave_bypass_condition": (
        "bypass : on ferme même si la pièce est fraîche"
    ),
    "comfort_reopen_label": "Réouverture confort",
    "comfort_reopen_condition": (
        "T°int < 21 °C ET T°ext < 22 °C simultanément"
    ),
    "close_step_label": "Avant fermeture",
    "close_step_duration": "10 min de conditions favorables",
    "open_step_label": "Avant réouverture",
    "open_step_duration": "20 min de luminosité insuffisante",
    "facade_orientation_label": "Orientation de la façade",
    "half_arc_label": "Demi-arc accepté",
    "min_elevation_param_label": "Élévation minimale",
    "min_uv_param_label": "Indice UV minimum",
    "target_position_param_label": "Position cible (volets fermés)",
    "indoor_temp_sensor_label": "Capteur de T° intérieure",
    "not_configured": "non configuré",
    # v0.9.11 — état coloré et formatage local
    "decimal_sep": ",",
    "state_active": "Active",
    "state_inactive": "Inactive",
    "override_none": "Aucun",
    "override_active_prefix": "Jusqu'à",
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
    "lux_margin": "Lux",
    "elevation_margin": "Elevation",
    "uv_margin": "UV",
    "azimuth_diff": "Azimuth",
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
    "lux_short": "Lux",
    "sun_facing_short": "Facing",
    "elevation_short": "Elev.",
    "all_covers": "Configured covers",
    # « Decision parameters » — v0.9.10 rewrite mirroring the
    # French rework: status at top, narrative pipeline.
    "decision_state": "Decision state",
    "current_status": "Current status",
    "protection_active": "Sun protection active",
    "manual_override": "Manual override",
    "override_reset_note": "auto-reset at 04:00 every day",
    "close_conditions": "Close conditions",
    "close_conditions_intro": (
        "Every condition below must be satisfied for the engine "
        "to trigger the close."
    ),
    "sun_position_section": "Sun position",
    "sun_position_intro": (
        "The sun must be high enough and inside the façade's "
        "acceptance arc."
    ),
    "outdoor_temp_section": "Outdoor temperature",
    "outdoor_temp_intro": (
        "Sun protection only triggers above an outdoor warmth "
        "threshold to preserve solar gain in cool seasons."
    ),
    "lux_section": "Outdoor brightness",
    "lux_intro": (
        "The lux threshold depends on the outdoor thermal regime "
        "(the warmer it is, the less sun is needed to close)."
    ),
    "uv_section": "UV index (optional)",
    "uv_intro": (
        "Extra filter, disabled if no UV sensor is configured "
        "on the hub."
    ),
    "comfort_section": "Indoor comfort (optional)",
    "comfort_intro": (
        "The room must already be warm to justify closing — "
        "prevents shading a cool room in the morning."
    ),
    "timing_section": "Timing",
    "timing_intro": (
        "Conditions must hold for a while before the engine "
        "acts, so a passing cloud doesn't toggle the shutters. "
        "The counter below reflects whichever phase is currently "
        "active (close or reopen)."
    ),
    "config_section": "Subentry configuration",
    "config_intro": (
        "Static values set when the group was created or edited."
    ),
    "criterion": "Criterion",
    "current_value": "Current value",
    "condition": "Condition",
    "indicator": "Indicator",
    "value": "Value",
    "step": "Step",
    "duration": "Duration",
    "current_counter": "Current counter",
    "parameter": "Parameter",
    "elevation_label": "Elevation",
    "elevation_condition": (
        "≥ {min}° (exit at {exit}°, hysteresis −{hys}°)"
    ),
    "azimuth_diff_label": "Offset from façade",
    "azimuth_diff_condition": (
        "≤ {arc}° (exit at {exit}°, hysteresis +{hys}°)"
    ),
    "outdoor_temp_label": "Outdoor T°",
    "outdoor_temp_condition": "≥ 20 °C to enable protection",
    "thermal_regime_label": "Thermal regime",
    "thermal_regime_value": "depends on outdoor T°",
    "thermal_regime_condition": (
        "mid-season (20–24 °C) · warm (24–30 °C) · "
        "heatwave (≥ 30 °C)"
    ),
    "outdoor_lux_label": "Outdoor brightness",
    "outdoor_lux_condition": "≥ {threshold_template} lx",
    "lux_threshold_label": "Adaptive threshold",
    "lux_threshold_value": "depends on outdoor T°",
    "lux_threshold_condition": (
        "mid-season: 70 000 lx · warm: 50 000 lx · "
        "heatwave: 35 000 lx"
    ),
    "lux_reopen_label": "Reopen",
    "lux_reopen_condition": "drops below 25 000 lx for 20 min",
    "uv_index_label": "UV index",
    "uv_index_condition": "≥ {min} (configured threshold)",
    "indoor_temp_label": "Indoor T°",
    "indoor_temp_condition": (
        "≥ 23 °C in warm regime / 24 °C in mid-season"
    ),
    "heatwave_bypass_label": "Heatwave regime",
    "heatwave_bypass_value": "Outdoor T° ≥ 30 °C",
    "heatwave_bypass_condition": (
        "bypass: close even if the room is cool"
    ),
    "comfort_reopen_label": "Comfort reopen",
    "comfort_reopen_condition": (
        "Indoor < 21 °C AND outdoor < 22 °C simultaneously"
    ),
    "close_step_label": "Before close",
    "close_step_duration": "10 min of favourable conditions",
    "open_step_label": "Before reopen",
    "open_step_duration": "20 min of insufficient brightness",
    "facade_orientation_label": "Façade orientation",
    "half_arc_label": "Accepted half-arc",
    "min_elevation_param_label": "Minimum elevation",
    "min_uv_param_label": "Minimum UV index",
    "target_position_param_label": "Target position (closed)",
    "indoor_temp_sensor_label": "Indoor T° sensor",
    "not_configured": "not configured",
    # v0.9.11 — colored state + locale-aware formatting
    "decimal_sep": ".",
    "state_active": "Active",
    "state_inactive": "Inactive",
    "override_none": "None",
    "override_active_prefix": "Until",
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


def _sun_tile(
    subentry: ConfigSubentry, labels: dict[str, str]
) -> dict[str, Any]:
    """Cockpit tile for a sun-protection subentry.

    Rendered as a ``glance`` card showing four key indicators at a
    glance (status, lux, sun_facing, elevation). Each entity also
    carries its own ``tap_action: navigate`` so a click anywhere
    on the card opens the drill-down — HA's ``glance`` ignores the
    card-level ``tap_action`` when entities are declared (they
    default to ``more-info``), so the per-entity override is
    required to restore the one-click navigation behaviour.
    """
    prefix = _entity_prefix(subentry)
    nav = _navigate_to(_view_path(subentry))
    return {
        "type": "glance",
        "title": subentry.title,
        "show_state": True,
        "state_color": True,
        "columns": 4,
        "tap_action": nav,
        "entities": [
            {
                "entity": f"sensor.{prefix}_sun_protection_status",
                "name": labels["status"],
                "tap_action": nav,
            },
            {
                "entity": f"sensor.{prefix}_sun_protection_lux",
                "name": labels["lux_short"],
                "tap_action": nav,
            },
            {
                "entity": f"binary_sensor.{prefix}_sun_facing",
                "name": labels["sun_facing_short"],
                "tap_action": nav,
            },
            {
                "entity": f"sensor.{prefix}_sun_protection_sun_elevation",
                "name": labels["elevation_short"],
                "tap_action": nav,
            },
        ],
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

    # Each cockpit section bundles its title and content in a single
    # vertical-stack so Lovelace's auto-column layout cannot orphan
    # the title in a different column from its tiles or entities
    # (same fix pattern as the « Marges » section in v0.8.3).
    def _section(title_key: str, content: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "vertical-stack",
            "cards": [
                {
                    "type": "markdown",
                    "content": f"### {labels[title_key]}",
                },
                content,
            ],
        }

    if schedules:
        cards.append(
            _section(
                "schedules",
                {
                    "type": "grid",
                    "columns": 1,
                    "square": False,
                    "cards": [
                        _scheduler_tile(sub) for sub in schedules
                    ],
                },
            )
        )
    if sims:
        cards.append(
            _section(
                "simulations",
                {
                    "type": "grid",
                    "columns": 1,
                    "square": False,
                    "cards": [_scheduler_tile(sub) for sub in sims],
                },
            )
        )
    if suns:
        cards.append(
            _section(
                "sun_protections",
                {
                    "type": "grid",
                    "columns": 1,
                    "square": False,
                    "cards": [_sun_tile(sub, labels) for sub in suns],
                },
            )
        )

    # Global list of every cover declared in any subentry, deduplicated
    # and sorted alphabetically. Gives one-click access to each shutter
    # without diving into a specific drill-down.
    all_covers: set[str] = set()
    for sub in entry.subentries.values():
        for cover_id in sub.data.get(CONF_COVERS) or []:
            if cover_id:
                all_covers.add(cover_id)
    if all_covers:
        cards.append(
            _section(
                "all_covers",
                {
                    "type": "entities",
                    "show_header_toggle": False,
                    "entities": sorted(all_covers),
                },
            )
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

    Two distinct paths can produce a non-numeric state on a margin
    sensor and we want to handle both cleanly:

    * **Protection deliberately not applicable** — e.g. lux_margin
      returns ``None`` whenever ``t_ext < T_OUTDOOR_NO_PROTECT``
      because the integration intentionally disables sun protection
      in cold weather to keep the solar gain. The margin loses its
      operational meaning and HA exposes ``unknown``.
    * **Upstream sensor unavailable** — the lux / UV / temperature
      provider drops out, propagating to ``unavailable``.

    In both cases a bare ``gauge`` card surfaces « L'entité n'est
    pas numérique ». Wrapping it in a ``conditional`` hides the
    card cleanly; it reappears automatically when the entity reads
    a number again.
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


def _decision_parameters_markdown(
    subentry: ConfigSubentry,
    labels: dict[str, str],
) -> dict[str, Any]:
    """Narrative markdown summary of the sun-protection decision.

    Three top-level sections — ``État de la décision`` (state),
    ``Conditions de fermeture`` (close conditions, ordered like
    ``_compute_decision``), ``Configuration de la sous-entrée``.
    Each close condition gets its own H3 with an intro paragraph
    and a 3-column table (Criterion / Current value / Condition).
    Static constants come from ``const.py``; per-subentry config
    is inlined; live values use Jinja ``{{ states('...') }}``
    templates re-rendered by HA's markdown card.
    """
    prefix = _entity_prefix(subentry)
    arc = subentry.data.get(CONF_ARC, DEFAULT_ARC)
    min_elevation = subentry.data.get(
        CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION
    )
    min_uv = subentry.data.get(CONF_MIN_UV, DEFAULT_MIN_UV)
    orientation = subentry.data.get(CONF_ORIENTATION, DEFAULT_ORIENTATION)
    target_position = subentry.data.get(
        CONF_TARGET_POSITION, DEFAULT_TARGET_POSITION
    )
    temp_indoor_entity = subentry.data.get(CONF_TEMP_INDOOR_ENTITY) or ""

    az_diff = f"sensor.{prefix}_sun_protection_azimuth_diff"
    elevation = f"sensor.{prefix}_sun_protection_sun_elevation"
    lux = f"sensor.{prefix}_sun_protection_lux"
    lux_threshold = f"sensor.{prefix}_sun_protection_lux_threshold"
    uv = f"sensor.{prefix}_sun_protection_uv_index"
    temp_outdoor = f"sensor.{prefix}_sun_protection_temp_outdoor"
    temp_indoor = f"sensor.{prefix}_sun_protection_temp_indoor"
    pending = f"sensor.{prefix}_sun_protection_pending_seconds"
    status = f"sensor.{prefix}_sun_protection_status"
    protection_active = f"binary_sensor.{prefix}_sun_protection_active"
    override = f"sensor.{prefix}_sun_protection_override_until"

    L = labels
    sep = L["decimal_sep"]
    elev_exit = max(0, min_elevation - ELEVATION_HYSTERESIS_DEG)
    arc_exit = arc + ARC_HYSTERESIS_DEG

    # --- Jinja value formatters (locale-aware) ----------------------------
    # Integer rounding for elevation, azimuth offset, lux, UV, pending sec.
    # Single-decimal rounding for temperatures, with `,` decimal separator
    # in FR (and `.` in EN) via a final `replace`. Both helpers short-
    # circuit non-numeric states (`unknown`/`unavailable`/…) to « — »
    # rather than letting `float(0)` coerce them to a misleading 0.
    def num0(state_entity: str) -> str:
        return (
            "{% set v = states('" + state_entity + "') %}"
            "{{ '—' if not is_number(v) else v | float | round(0) | int }}"
        )

    def num1(state_entity: str) -> str:
        return (
            "{% set v = states('" + state_entity + "') %}"
            "{{ '—' if not is_number(v) else "
            "('%.1f' | format(v | float) | replace('.', '" + sep + "')) }}"
        )

    lux_threshold_template = num0(lux_threshold)

    # --- État de la décision ------------------------------------------------
    # The current status is rendered as a colored <ha-alert> banner. It is
    # the single most important "why am I in this state?" signal, and
    # ha-alert is the only sanitizer-safe way to get theme colors in a
    # markdown card: HA strips inline `style` attributes, so a
    # <span style="color: …"> renders colorless. ha-alert exposes four
    # types — info (blue) / warning (orange) / error (red) / success
    # (green) — onto which we fold the decision palette: warning for an
    # engaged or closing protection, error for a misconfiguration, and
    # info (the default) for user control (override/disabled) and every
    # idle/standby state. state_translated() supplies the human label.
    status_banner = (
        "{% set s = states('" + status + "') %}"
        "{% set t = {"
        "'active': 'warning',"
        "'pending_close': 'warning',"
        "'no_sensor': 'error'"
        "}.get(s, 'info') %}"
        '<ha-alert alert-type="{{ t }}" title="' + L["current_status"] + '">'
        "{{ state_translated('" + status + "') }}"
        "</ha-alert>"
    )
    # Protection active: the binary_sensor has no device_class so
    # state_translated() would return raw on/off → a small if/else with
    # our own labels, the active state emphasized in bold.
    protection_cell = (
        "{% if is_state('" + protection_active + "', 'on') %}"
        "<strong>" + L["state_active"] + "</strong>"
        "{% else %}"
        + L["state_inactive"] +
        "{% endif %}"
    )
    # Override: timestamp sensor. When unknown/unavailable/none, render
    # « Aucun » and drop the reset note (which only makes sense for an
    # active override). When set, render the formatted HH:MM in bold
    # followed by the reset note in regular text.
    override_cell = (
        "{% set v = states('" + override + "') %}"
        "{% if v in ['unknown', 'unavailable', 'none', ''] %}"
        + L["override_none"] +
        "{% else %}"
        "<strong>" + L["override_active_prefix"] + " "
        "{{ as_timestamp(v) | timestamp_custom('%H:%M', true) }}"
        "</strong> (" + L["override_reset_note"] + ")"
        "{% endif %}"
    )

    # --- Capteur de T° intérieure : valeur live (Configuration) -----------
    if temp_indoor_entity:
        indoor_sensor_repr = num1(temp_indoor_entity) + " °C"
    else:
        indoor_sensor_repr = L["not_configured"]

    content = (
        f"## {L['decision_state']}\n\n"
        f"{status_banner}\n\n"
        f"| {L['indicator']} | {L['value']} |\n"
        f"|---|---|\n"
        f"| {L['protection_active']} | {protection_cell} |\n"
        f"| {L['manual_override']} | {override_cell} |\n\n"
        f"## {L['close_conditions']}\n\n"
        f"{L['close_conditions_intro']}\n\n"
        # 1. Sun position
        f"### 1. {L['sun_position_section']}\n\n"
        f"{L['sun_position_intro']}\n\n"
        f"| {L['criterion']} | {L['current_value']} | "
        f"{L['condition']} |\n"
        f"|---|---|---|\n"
        f"| {L['elevation_label']} | {num0(elevation)}° | "
        + L['elevation_condition'].format(
            min=min_elevation,
            exit=elev_exit,
            hys=ELEVATION_HYSTERESIS_DEG,
        )
        + " |\n"
        f"| {L['azimuth_diff_label']} | {num0(az_diff)}° | "
        + L['azimuth_diff_condition'].format(
            arc=arc,
            exit=arc_exit,
            hys=ARC_HYSTERESIS_DEG,
        )
        + " |\n\n"
        # 2. Outdoor temperature
        f"### 2. {L['outdoor_temp_section']}\n\n"
        f"{L['outdoor_temp_intro']}\n\n"
        f"| {L['criterion']} | {L['current_value']} | "
        f"{L['condition']} |\n"
        f"|---|---|---|\n"
        f"| {L['outdoor_temp_label']} | {num1(temp_outdoor)} °C | "
        f"{L['outdoor_temp_condition']} |\n"
        f"| {L['thermal_regime_label']} | "
        f"{L['thermal_regime_value']} | "
        f"{L['thermal_regime_condition']} |\n\n"
        # 3. Brightness
        f"### 3. {L['lux_section']}\n\n"
        f"{L['lux_intro']}\n\n"
        f"| {L['criterion']} | {L['current_value']} | "
        f"{L['condition']} |\n"
        f"|---|---|---|\n"
        f"| {L['outdoor_lux_label']} | {num0(lux)} lx | "
        + L['outdoor_lux_condition'].format(
            threshold_template=lux_threshold_template
        )
        + " |\n"
        f"| {L['lux_threshold_label']} | "
        f"{L['lux_threshold_value']} | "
        f"{L['lux_threshold_condition']} |\n"
        f"| {L['lux_reopen_label']} | — | "
        f"{L['lux_reopen_condition']} |\n\n"
        # 4. UV
        f"### 4. {L['uv_section']}\n\n"
        f"{L['uv_intro']}\n\n"
        f"| {L['criterion']} | {L['current_value']} | "
        f"{L['condition']} |\n"
        f"|---|---|---|\n"
        f"| {L['uv_index_label']} | {num1(uv)} | "
        + L['uv_index_condition'].format(min=min_uv)
        + " |\n\n"
        # 5. Indoor comfort
        f"### 5. {L['comfort_section']}\n\n"
        f"{L['comfort_intro']}\n\n"
        f"| {L['criterion']} | {L['current_value']} | "
        f"{L['condition']} |\n"
        f"|---|---|---|\n"
        f"| {L['indoor_temp_label']} | {num1(temp_indoor)} °C | "
        f"{L['indoor_temp_condition']} |\n"
        f"| {L['heatwave_bypass_label']} | "
        f"{L['heatwave_bypass_value']} | "
        f"{L['heatwave_bypass_condition']} |\n"
        f"| {L['comfort_reopen_label']} | — | "
        f"{L['comfort_reopen_condition']} |\n\n"
        # 6. Timing
        f"### 6. {L['timing_section']}\n\n"
        f"{L['timing_intro']}\n\n"
        f"| {L['step']} | {L['duration']} | "
        f"{L['current_counter']} |\n"
        f"|---|---|---|\n"
        f"| {L['close_step_label']} | "
        f"{L['close_step_duration']} | {num0(pending)} s |\n"
        f"| {L['open_step_label']} | "
        f"{L['open_step_duration']} | {num0(pending)} s |\n\n"
        # Configuration
        f"## {L['config_section']}\n\n"
        f"{L['config_intro']}\n\n"
        f"| {L['parameter']} | {L['value']} |\n"
        f"|---|---|\n"
        f"| {L['facade_orientation_label']} | {orientation}° |\n"
        f"| {L['half_arc_label']} | {arc}° |\n"
        f"| {L['min_elevation_param_label']} | {min_elevation}° |\n"
        f"| {L['min_uv_param_label']} | {min_uv} |\n"
        f"| {L['target_position_param_label']} | {target_position} % |\n"
        f"| {L['indoor_temp_sensor_label']} | {indoor_sensor_repr} |\n"
    )
    return {"type": "markdown", "content": content}


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
    orientation = subentry.data.get(CONF_ORIENTATION, DEFAULT_ORIENTATION)
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

    # Narrative recap of every decision input: status at the top,
    # then the close-condition pipeline section by section, then
    # the static configuration. Live values land via Jinja
    # templates that HA refreshes on every state change.
    cards.append(_decision_parameters_markdown(subentry, labels))

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
                minimum=-LUX_MILD,
                maximum=LUX_MILD,
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
