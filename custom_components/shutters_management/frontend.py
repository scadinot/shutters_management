"""Ressources statiques du frontend : la carte Lovelace personnalisée.

Extrait d'``__init__.py`` sans modification.

Ce module porte le même nom que le dossier d'actifs ``frontend/`` voisin, qui
contient le JavaScript de la carte. Ce n'est pas un conflit : ce dossier n'a pas
d'``__init__.py``, et un module l'emporte sur un paquet d'espace de noms —
vérifié. ``Path(__file__).parent / _FRONTEND_DIR`` continue de désigner le
dossier, le nom étant résolu sur le disque et non par l'importateur. Si le
dossier devenait un paquet régulier, l'import d'``__init__.py`` échouerait
bruyamment au chargement de l'intégration, et la porte de contrôle d'imports le
verrait.

Le nom ne masque pas non plus ``homeassistant.components.frontend`` : Python 3
n'utilise que des imports absolus.
"""
from __future__ import annotations

import logging


from homeassistant.core import (
    HomeAssistant,
)

from .const import (
    DOMAIN,
)
_LOGGER = logging.getLogger(__name__)


_FRONTEND_DIR = "frontend"
_FRONTEND_URL = f"/{DOMAIN}_frontend"
_CARD_URL = f"{_FRONTEND_URL}/shutters-sun-3d-card.js"
_FRONTEND_REGISTERED_FLAG = f"{DOMAIN}_frontend_registered"


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve the custom Lovelace card and register it as a frontend module.

    Idempotent across reloads of the integration: a flag in
    ``hass.data`` guards a second registration attempt. Removing
    static paths or extra JS modules requires a HA restart, which is
    acceptable for a ``single_config_entry`` integration.

    Defensive against test harnesses where the ``frontend`` component
    is not fully set up: ``DATA_EXTRA_MODULE_URL`` is initialized via
    ``setdefault`` so ``add_extra_js_url`` does not KeyError.
    """
    if hass.data.get(_FRONTEND_REGISTERED_FLAG):
        return
    from pathlib import Path

    from homeassistant.components.frontend import (
        DATA_EXTRA_MODULE_URL,
        add_extra_js_url,
    )
    from homeassistant.components.http import StaticPathConfig

    frontend_path = Path(__file__).parent / _FRONTEND_DIR
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_FRONTEND_URL, str(frontend_path), False)]
    )
    hass.data.setdefault(DATA_EXTRA_MODULE_URL, set())
    add_extra_js_url(hass, _CARD_URL)
    hass.data[_FRONTEND_REGISTERED_FLAG] = True
