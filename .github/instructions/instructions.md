# Instructions Claude Code

Utilise le français pour toutes tes interactions.

## Tests et validation

Avant tout commit ou push :

1. Tests unitaires : `pytest -q`
2. Couverture : `pytest --cov=custom_components.shutters_management --cov-report=term-missing`
3. Validation Python : `python3 -m py_compile custom_components/shutters_management/*.py`
4. Validation JSON :
   ```bash
   python3 -c "import json; \
   [json.load(open(f)) for f in ('custom_components/shutters_management/strings.json', \
     'custom_components/shutters_management/translations/en.json', \
     'custom_components/shutters_management/translations/fr.json', \
     'custom_components/shutters_management/manifest.json')]"
   ```

## Conventions de développement

- Branche de développement : `claude/shutters-management-integration-FJUT4`.
- Ne JAMAIS pousser directement sur `main` — toujours via une pull
  request.
- Sujet de commit court à l'impératif ; le corps explique le **pourquoi**
  et non le quoi (le diff parle de lui-même).
- Tout changement du `config_flow` doit synchroniser `strings.json` +
  `translations/en.json` + `translations/fr.json`.
- Tout changement de schéma de données (clé ajoutée/supprimée/renommée
  dans `entry.data` ou `subentry.data`) doit s'accompagner :
  - d'une bump de `VERSION` dans `config_flow.py`,
  - d'un bloc `if entry.version < N:` dans
    `__init__.py:async_migrate_entry`,
  - d'un test dans `tests/test_migration.py`.
- Tout nouveau champ utilisateur doit avoir un `DEFAULT_*` dans
  `const.py`.

## Pipeline CI

Trois workflows GitHub Actions doivent passer pour qu'une PR soit
mergeable :

- `tests.yaml` — pytest sur Python 3.12 et 3.13.
- `Validate HACS.yaml` — conformité HACS.
- `Validate Hassfest.yaml` — conformité Home Assistant.

## Architecture du projet

L'intégration suit le pattern **hub + sous-entrées** :

- Un **hub** unique (`TYPE_HUB`) porte les canaux partagés
  (`notify_services`, `tts_engine`, `tts_targets`, `presence_entity`)
  et les capteurs Sun Protection.
- Trois types de **sous-entrée** :
  - `instance` — planification déterministe (Bureau, RDC, …).
  - `presence_simulation` — simulation aléatoire avec mode
    « uniquement en absence ».
  - `sun_protection` — protection solaire d'un groupe de volets.

Chaque sous-entrée porte ses propres modes `notify_mode` et `tts_mode`
(depuis v0.7.0).
