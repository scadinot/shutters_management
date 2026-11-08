"""Charge chaque module du paquet : détecte boucles d'imports et symboles manquants.

La suite pytest ne peut pas s'exécuter sous Windows (``homeassistant/runner.py``
importe ``fcntl``, exclusif à Unix). Ce contrôle est la vérification locale qui
reste disponible : il charge tous les modules du paquet, ce qui fait apparaître
immédiatement une boucle d'imports ou un symbole absent, et vérifie que les
quatre noms dont dépendent Home Assistant et les tests sont bien ré-exportés par
``__init__.py``.

Usage : ``python scripts/check_imports.py [racine_du_depot]``
Code de sortie 0 si tout charge et si les quatre ré-exports sont présents.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

# Home Assistant cherche ``async_migrate_entry`` sur le module de l'intégration ;
# les trois autres sont importés depuis le paquet par cinq fichiers de tests.
REEXPORTS = (
    "ShuttersScheduler",
    "ShuttersSunProtectionManager",
    "_async_restore_cover_positions",
    "async_migrate_entry",
)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    sys.path.insert(0, str(root / "custom_components"))
    pkg = importlib.import_module("shutters_management")

    loaded: list[str] = []
    failures: list[tuple[str, str]] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        try:
            importlib.import_module(f"shutters_management.{info.name}")
            loaded.append(info.name)
        except Exception as err:  # noqa: BLE001 - on veut rapporter tout échec
            failures.append((info.name, f"{type(err).__name__}: {err}"))

    print(f"Modules charges ({len(loaded)}) :", ", ".join(loaded))
    for name, err in failures:
        print("ECHEC import :", name, "->", err)

    missing = [name for name in REEXPORTS if not hasattr(pkg, name)]
    for name in REEXPORTS:
        print(f"re-export {name} :", "ABSENT" if name in missing else "present")

    return 1 if failures or missing else 0


if __name__ == "__main__":
    sys.exit(main())
