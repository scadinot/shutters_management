# Découpage de `__init__.py` — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Répartir les 2 278 lignes de `custom_components/shutters_management/__init__.py` en huit modules dédiés, sans aucun changement de comportement.

**Architecture:** Déplacement pur, de bas en haut d'un graphe de dépendances acyclique : `presence` → `notifications` → `sun_protection` → `scheduler` → `migrations` → `services` → `frontend`. `__init__.py` ne garde que le cycle de vie de l'entrée et ré-exporte quatre noms pour Home Assistant et pour les tests. Aucun module métier n'importe `__init__.py`.

**Tech Stack:** Python 3.13, Home Assistant ≥ 2026.3, pytest + `pytest-homeassistant-custom-component`, ruff (contrôle statique local uniquement), GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-11-08-decoupage-init-design.md`](../specs/2026-11-08-decoupage-init-design.md)

## Global Constraints

- **Déplacement pur.** Aucun renommage, aucune réécriture, aucune optimisation au passage. Les helpers gardent leur underscore initial.
- **Aucun module métier n'importe `__init__.py`.** Les imports vont toujours vers le bas du graphe.
- **`__init__.py` ré-exporte quatre noms**, obligatoires : `ShuttersScheduler`, `ShuttersSunProtectionManager`, `_async_restore_cover_positions`, `async_migrate_entry`. Home Assistant cherche le dernier sur le module de l'intégration ; les cinq fichiers de tests qui importent depuis le paquet ne doivent pas changer.
- **Les blocs se repèrent par symbole, jamais par numéro de ligne.** Les numéros donnés ici valent pour le commit `080b09f` et se décalent après chaque tâche.
- **`_LOGGER = logging.getLogger(__name__)` dans chaque nouveau module.** Conséquence assumée : les lignes de log déplacées portent désormais le nom du sous-module (`…shutters_management.scheduler`). La configuration `logger:` des utilisateurs n'est pas affectée, les loggers enfants héritant du parent. À mentionner au CHANGELOG.
- **Un échec de test invalide l'étape.** On corrige le déplacement, on n'adapte pas un test pour le faire passer.
- **Les tests existants ne changent que par leurs chaînes de cible `patch()`** — 18 au total. Les 25 cibles vers `.const` et les 2 vers `.panel` restent valides : ne pas y toucher. Aucune logique de test existante n'est modifiée.
- **Écart assumé sur l'ordre de travail de la spec**, qui liste « tests » en dernier : ce plan replie la réécriture de chaque chaîne de cible dans la tâche qui déplace le symbole visé (1 en tâche 4, 17 en tâche 5). Même diff final, mais chaque commit reste au vert sous la porte C au lieu d'en laisser cinq au rouge.
- **`.gitignore` contient déjà `.venv/`** (commit `080b09f`) : rien à reprendre côté livraison.
- **Chaque commit se termine par** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Version cible 0.9.28**, une seule pull request.

### Portes de vérification

Les trois commandes ci-dessous, depuis la racine du dépôt. Elles sont rappelées
`Porte A/B/C` dans les tâches.

```bash
./.venv/Scripts/python.exe scripts/check_imports.py .
```

```bash
./.venv/Scripts/python.exe -m ruff check --select F401,F811,F821 --output-format=concise custom_components/shutters_management/
```

- **Porte A — contrôle d'imports.** Attendu : tous les modules chargés, les quatre ré-exports présents, code de sortie 0. Détecte les boucles d'imports et les symboles absents à l'import.
- **Porte B — contrôle statique.** Attendu : **exactement** les 4 constats de référence, tous dans `config_flow.py` (`MODE_ALWAYS`, `MODE_AWAY_ONLY`, `MODE_DISABLED`, `MODE_HOME_ONLY` importés mais inutilisés), hors périmètre T1. Tout constat supplémentaire invalide l'étape. C'est cette porte, et non la porte A, qui attrape un helper déplacé qui appelle un symbole non importé (F821) et les imports devenus inutiles dans `__init__.py` (F401).
- **Porte C — CI.** `gh pr checks` sur la pull request ouverte en tâche 1 : les 190+ tests sur Python 3.13, plus HACS et Hassfest. `tests.yaml` se déclenche sur `pull_request`, donc chaque poussée rejoue la suite. **La suite de tests ne peut pas s'exécuter sous Windows** (`homeassistant/runner.py` importe `fcntl`, exclusif à Unix) : la CI est le seul moyen de la faire tourner.

## Review Focus

Classes d'entrées que la spec implique et qu'aucun test existant n'exerce, les
plus susceptibles de gêner un utilisateur en premier. Chaque ligne reçoit un
test dans la tâche qui détient le code.

1. **Ressources frontend enregistrées deux fois** — `_async_register_frontend_resources` n'est couvert par aucun test. Après déplacement, un second `async_setup_entry` doit sortir sur le drapeau `_FRONTEND_REGISTERED_FLAG` sans réappeler `add_extra_js_url`, sinon la carte 3D est injectée en double dans toutes les pages. → tâche 8.
2. **`presence_entity` stocké en chaîne simple** — la branche `isinstance(raw, str)` de `_is_away_for` existe mais n'est testée que du côté migration. Un hub dont la donnée n'a pas été normalisée doit continuer à être lu. → tâche 2.
3. **Toutes les entités de présence indisponibles** — `_is_away_for` doit alors retomber sur le balayage `person.*`, et non répondre « maison occupée ». Branche non couverte. → tâche 2.
4. **Services après deux rechargements consécutifs** — `_async_register_services` se garde sur `has_service` et sa fermeture `_schedulers()` lit `hass.data[DOMAIN]` en direct. Les tests ne couvrent qu'une mise en place unique ; après deux rechargements, `run_now` doit atteindre les instances courantes et non des fermetures périmées. → tâche 7.
5. **Nom du logger dans les enregistrements** — il passe de `custom_components.shutters_management` au nom du sous-module. Invisible pour la suite actuelle, qui n'assure que sur `record.message`, mais visible dans les journaux de l'utilisateur. → tâche 5.

---

### Task 1: Portes de vérification et pull request de travail

**Files:**
- Create: `scripts/check_imports.py`
- Modify: `README.md` (arborescence du dépôt, ajouter `scripts/`)

**Interfaces:**
- Consumes: rien.
- Produces: `scripts/check_imports.py`, exécutable par `python scripts/check_imports.py <racine>`, code de sortie 0 si tous les modules du paquet se chargent et si les quatre ré-exports sont présents, 1 sinon. Toutes les tâches suivantes l'appellent (porte A).

- [ ] **Step 1: Écrire `scripts/check_imports.py`**

Charge le paquet depuis `<racine>/custom_components`, importe chaque module
listé par `pkgutil.iter_modules`, puis vérifie les quatre ré-exports.

```python
"""Charge chaque module du paquet : détecte boucles d'imports et symboles manquants."""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

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
        except Exception as err:  # noqa: BLE001 - on veut tout rapporter
            failures.append((info.name, f"{type(err).__name__}: {err}"))
    print("Modules charges :", ", ".join(loaded))
    for name, err in failures:
        print("ECHEC import :", name, "->", err)
    missing = [name for name in REEXPORTS if not hasattr(pkg, name)]
    for name in REEXPORTS:
        print(f"re-export {name} :", "ABSENT" if name in missing else "present")
    return 1 if failures or missing else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Installer ruff dans le venv local**

Run: `./.venv/Scripts/python.exe -m pip install ruff`

Aucune configuration ruff n'est ajoutée au dépôt : le dépôt ne lint pas
aujourd'hui, et T1 n'est pas le moment de l'imposer. Les règles passent par
`--select` en ligne de commande.

- [ ] **Step 3: Relever la référence des deux portes locales sur le code intact**

Run: porte A, puis porte B.
Expected: porte A code 0, 9 modules chargés, 4 ré-exports présents. Porte B
exactement 4 constats F401, tous dans `config_flow.py`.

- [ ] **Step 4: Ajouter `scripts/` à l'arborescence du README**

Une ligne dans le bloc `Structure du dépôt`, après `custom_components/` :
`├── scripts/                   # outillage de développement`, avec
`│   └── check_imports.py` en dessous.

- [ ] **Step 5: Commit et ouverture de la pull request en brouillon**

```bash
git add scripts/check_imports.py README.md
git commit -m "chore: ajoute le controle d'imports du paquet"
git push -u origin claude/split-init-modules
gh pr create --draft --title "refactor: decoupe __init__.py en modules dedies" --body-file <fichier>
```

Le brouillon existe pour que `tests.yaml`, déclenché sur `pull_request`,
rejoue les 190+ tests à chaque poussée. C'est la porte C de toutes les tâches
suivantes.

---

### Task 2: `presence.py`

**Files:**
- Create: `custom_components/shutters_management/presence.py`
- Modify: `custom_components/shutters_management/__init__.py` (retirer `_is_away_for`, lignes 338-379 ; ajouter `from .presence import _is_away_for`)
- Test: `tests/test_presence.py` (créer)

**Interfaces:**
- Consumes: porte A de la tâche 1.
- Produces: `_is_away_for(hass: HomeAssistant, hub_data: Mapping[str, Any]) -> bool`. Consommé par `notifications.py` (tâche 3) et `scheduler.py` (tâche 5).

- [ ] **Step 1: Écrire les tests en échec des deux branches non couvertes**

```python
async def test_is_away_for_accepts_a_bare_string(hass: HomeAssistant) -> None:
    hass.states.async_set("person.alice", "not_home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: "person.alice"}) is True
    hass.states.async_set("person.alice", "home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: "person.alice"}) is False


async def test_is_away_for_falls_back_to_person_scan(hass: HomeAssistant) -> None:
    """Toutes les entités configurées indisponibles → balayage person.*."""
    hass.states.async_set("group.presence", STATE_UNAVAILABLE)
    hass.states.async_set("person.alice", "home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: ["group.presence"]}) is False
    hass.states.async_set("person.alice", "not_home")
    assert _is_away_for(hass, {CONF_PRESENCE_ENTITY: ["group.presence"]}) is True
```

Importer depuis `custom_components.shutters_management.presence`.

- [ ] **Step 2: Vérifier que les tests échouent**

Les tests ne peuvent pas s'exécuter sous Windows (porte C). Vérifier en local
que le module visé n'existe pas encore : `./.venv/Scripts/python.exe -c "import shutters_management.presence"` depuis `custom_components/` doit lever `ModuleNotFoundError`.

- [ ] **Step 3: Créer `presence.py` et y déplacer `_is_away_for`**

Le corps est repris sans la moindre modification. Le module importe
`CONF_PRESENCE_ENTITY` et `AWAY_STATES` depuis `.const`, `STATE_UNAVAILABLE` /
`STATE_UNKNOWN` depuis `homeassistant.const`, `HomeAssistant` depuis
`homeassistant.core`, `Mapping` depuis `collections.abc`, `Any` depuis `typing`,
et déclare son propre `_LOGGER`.

- [ ] **Step 4: Remplacer l'usage dans `__init__.py` par un import**

`from .presence import _is_away_for`. Les deux appelants internes
(`_async_dispatch_notifications`, `ShuttersScheduler._conditions_met`) restent
en place pour l'instant.

- [ ] **Step 5: Portes A et B**

Expected: porte A code 0 avec `presence` dans la liste des modules chargés ;
porte B toujours 4 constats, tous dans `config_flow.py`.

- [ ] **Step 6: Commit, puis porte C**

```bash
git add custom_components/shutters_management/presence.py custom_components/shutters_management/__init__.py tests/test_presence.py
git commit -m "refactor: extrait la presence du foyer dans presence.py"
git push
```

Attendre `gh pr checks` au vert avant la tâche suivante.

---

### Task 3: `notifications.py`

**Files:**
- Create: `custom_components/shutters_management/notifications.py`
- Modify: `custom_components/shutters_management/__init__.py`

**Interfaces:**
- Consumes: `_is_away_for` de `.presence` (tâche 2).
- Produces: `_async_dispatch_notifications(...)`, consommé par `sun_protection.py` (tâche 4) et `scheduler.py` (tâche 5), avec la signature actuelle inchangée.

- [ ] **Step 1: Déplacer les sept symboles**

Le bloc **n'est pas contigu** dans le fichier actuel : `_NOTIFY_HEADERS`
(234-245), `_TTS_HEADERS` (246-257), `_cover_display_name` (259-266),
`_notify_message` (267-284), `_tts_message` (286-302), puis, après trois blocs
qui partent ailleurs, `_async_dispatch_notifications` (382-413),
`_async_send_push` (415-461), `_async_send_tts` (463-500). Entre les deux
groupes se trouvent `_parse_time` / `_next_datetime_for` (→ tâche 5),
`_strip_name` (→ tâche 6) et `_is_away_for` (déjà parti en tâche 2) : ne pas
les emporter.

- [ ] **Step 2: Ajouter l'import dans `__init__.py`**

Aucun appelant ne reste dans `__init__.py` après ce déplacement : si la porte B
signale un F401 sur un symbole de notification, c'est que l'import ne doit pas
être ajouté. Les appelants restants sont dans les deux grosses classes, encore
en place ; elles importent donc depuis `.notifications`.

- [ ] **Step 3: Portes A et B**

Expected: porte A code 0, `notifications` chargé ; porte B inchangée.

- [ ] **Step 4: Commit, puis porte C**

```bash
git add custom_components/shutters_management/notifications.py custom_components/shutters_management/__init__.py
git commit -m "refactor: extrait notifications et TTS dans notifications.py"
git push
```

---

### Task 4: `sun_protection.py`

**Files:**
- Create: `custom_components/shutters_management/sun_protection.py`
- Modify: `custom_components/shutters_management/__init__.py`
- Test: `tests/test_sun_protection.py:559` (chaîne de cible seulement)

**Interfaces:**
- Consumes: `_async_dispatch_notifications` de `.notifications`, `ShuttersStateStore` de `.state_store`.
- Produces: `ShuttersSunProtectionManager`, `_async_restore_cover_positions`, `_restored_positions`, `_position_matches`. Les trois premiers sont consommés par `__init__.py`, le premier aussi par `switch.py`, `sensor.py` et `binary_sensor.py` (tâche 9).

- [ ] **Step 1: Déplacer les quatre symboles**

`_restored_positions` (158-167), `_position_matches` (169-182),
`_async_restore_cover_positions` (184-225) et `ShuttersSunProtectionManager`
(996-1778). `async_call_later`, `async_track_time_change`, `async_at_started`,
`HassJob` et `async_dispatcher_send` suivent les usages de la classe.

- [ ] **Step 2: Mettre à jour `__init__.py`**

`from .sun_protection import ShuttersSunProtectionManager, _async_restore_cover_positions, _restored_positions`.
Les trois sont réellement utilisés : la classe en `async_setup_entry` et dans
le `isinstance` d'`async_unload_entry`, les deux helpers dans
`async_remove_entry`.

- [ ] **Step 3: Réécrire la cible de `patch()` du test**

`tests/test_sun_protection.py:559` :
`_CALL_LATER = "custom_components.shutters_management.sun_protection.async_call_later"`.
Patcher le nom dans `__init__` ne patche plus celui que `sun_protection` a
importé. `scheduler.py` utilisera aussi `async_call_later` (tâche 5) : cette
cible-ci ne doit viser que `sun_protection`.

- [ ] **Step 4: Portes A et B**

Expected: porte A code 0 avec les ré-exports `ShuttersSunProtectionManager` et
`_async_restore_cover_positions` présents ; porte B inchangée.

- [ ] **Step 5: Commit, puis porte C**

```bash
git add custom_components/shutters_management/sun_protection.py custom_components/shutters_management/__init__.py tests/test_sun_protection.py
git commit -m "refactor: extrait le moteur de protection solaire dans sun_protection.py"
git push
```

La porte C de cette tâche est la plus informative du plan : `test_sun_protection.py`,
`test_position_tolerance.py` et `test_sun_mode_reload.py` traversent toutes les
coutures créées ici, dont l'appel de `async_remove_entry` vers
`_restored_positions` et `_async_restore_cover_positions`.

---

### Task 5: `scheduler.py`

**Files:**
- Create: `custom_components/shutters_management/scheduler.py`
- Modify: `custom_components/shutters_management/__init__.py`
- Test: `tests/test_sequential_covers.py`, `tests/test_notifications.py`, `tests/test_sun_trigger.py`, `tests/test_multi_instance.py` (chaînes de cible), `tests/test_scheduler.py` (nouveau test)

**Interfaces:**
- Consumes: `_is_away_for` de `.presence`, `_async_dispatch_notifications` de `.notifications`, `ShuttersStateStore` de `.state_store`.
- Produces: `ShuttersScheduler`, consommé par `__init__.py`, `services.py` (tâche 7), `switch.py`, `sensor.py`, `button.py` (tâche 9).

- [ ] **Step 1: Déplacer les trois symboles**

`_parse_time` (304-312), `_next_datetime_for` (314-329) et `ShuttersScheduler`
(1781-2278). Suivent les usages : `random`, `get_astral_event_next`,
`async_track_time_change`, `async_track_sunrise`, `async_track_sunset`,
`async_call_later`, `async_dispatcher_send`, `COVER_ACTION_TIMEOUT_SECONDS`.

- [ ] **Step 2: Mettre à jour `__init__.py`**

`from .scheduler import ShuttersScheduler` — utilisé en `async_setup_entry` et
dans le `isinstance` d'`async_unload_entry`.

- [ ] **Step 3: Réécrire les 17 chaînes de cible**

Préfixe `custom_components.shutters_management.` partout, remplacé par
`custom_components.shutters_management.scheduler.` :

| Symbole | Sites |
|---|---|
| `random.shuffle` | `test_sequential_covers.py:104,136,175,225,267,311,357,381` ; `test_notifications.py:156` |
| `get_astral_event_next` | `test_sun_trigger.py:76,101,137` |
| `async_track_time_change` | `test_sun_trigger.py:176` |
| `async_track_sunrise` | `test_sun_trigger.py:178` |
| `async_track_sunset` | `test_sun_trigger.py:180` |
| `async_dispatcher_send` | `test_multi_instance.py:132` |
| `COVER_ACTION_TIMEOUT_SECONDS` | `test_sequential_covers.py:178` |

Seule la chaîne change ; aucune assertion, aucun corps de test n'est touché.
`test_sun_trigger.py:184` continue d'affirmer `mock_time.assert_called_once()` :
la cible devient plus précise, puisque l'appel de `sun_protection` au même
traqueur n'est plus capté — l'entrée du test ne crée pas de sous-entrée de
protection solaire, donc le compte reste à un.

- [ ] **Step 4: Écrire le test en échec du nom de logger**

Dans `tests/test_scheduler.py`, un test qui épingle la conséquence assumée du
découpage :

```python
async def test_scheduler_logs_carry_the_submodule_logger_name(
    hass: HomeAssistant, caplog, base_config
) -> None:
    """Les lignes de log du planificateur portent le nom du sous-module."""
    # … mise en place menant à un enregistrement du planificateur …
    names = {r.name for r in caplog.records if "shutters_management" in r.name}
    assert "custom_components.shutters_management.scheduler" in names
```

- [ ] **Step 5: Portes A et B**

Expected: porte A code 0 avec le ré-export `ShuttersScheduler` présent ;
porte B inchangée. À ce stade `__init__.py` ne doit plus importer `random` ni
`get_astral_event_next` : un F401 sur l'un des deux signale un import oublié.

- [ ] **Step 6: Commit, puis porte C**

```bash
git add custom_components/shutters_management/scheduler.py custom_components/shutters_management/__init__.py tests/
git commit -m "refactor: extrait le planificateur dans scheduler.py"
git push
```

---

### Task 6: `migrations.py`

**Files:**
- Create: `custom_components/shutters_management/migrations.py`
- Modify: `custom_components/shutters_management/__init__.py`

**Interfaces:**
- Consumes: `.const` seulement.
- Produces: `async_migrate_entry(hass, entry) -> bool` et `_async_migrate_legacy_entries(hass) -> None`, tous deux consommés par `__init__.py`.

- [ ] **Step 1: Déplacer les trois symboles**

`_strip_name` (333-335), `_async_migrate_legacy_entries` (518-597) et
`async_migrate_entry` (760-915).

- [ ] **Step 2: Mettre à jour `__init__.py`**

`from .migrations import _async_migrate_legacy_entries, async_migrate_entry`.
`async_migrate_entry` **doit** rester visible sur le module du paquet : Home
Assistant le cherche là. Les 12 tests de `test_migration.py` passent tous par
`hass.config_entries.async_setup`, donc ils exercent réellement ce ré-export —
un import oublié les fait tous échouer, ce qui est le signal voulu.

- [ ] **Step 3: Portes A et B**

Expected: porte A code 0 avec le ré-export `async_migrate_entry` présent ;
porte B inchangée.

- [ ] **Step 4: Commit, puis porte C**

```bash
git add custom_components/shutters_management/migrations.py custom_components/shutters_management/__init__.py
git commit -m "refactor: extrait la chaine de migration dans migrations.py"
git push
```

---

### Task 7: `services.py`

**Files:**
- Create: `custom_components/shutters_management/services.py`
- Modify: `custom_components/shutters_management/__init__.py`
- Test: `tests/test_init.py` (nouveau test)

**Interfaces:**
- Consumes: `ShuttersScheduler` de `.scheduler` (tâche 5).
- Produces: `RUN_NOW_SCHEMA`, `_async_register_services(hass)`, `_async_unregister_services(hass)`, consommés par `__init__.py`.

- [ ] **Step 1: Écrire le test en échec des deux rechargements**

```python
async def test_services_survive_two_consecutive_reloads(
    hass: HomeAssistant, base_config
) -> None:
    """Après deux rechargements, run_now atteint les planificateurs courants."""
    # … mise en place du hub …
    for _ in range(2):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_RUN_NOW)
    scheduler = hass.data[DOMAIN][get_only_subentry_id(entry)]
    with patch.object(scheduler, "async_run_now") as run_now:
        await hass.services.async_call(
            DOMAIN, SERVICE_RUN_NOW, {ATTR_ACTION: ACTION_OPEN}, blocking=True
        )
    run_now.assert_called_once_with(ACTION_OPEN)
```

Ce test attrape une fermeture `_schedulers()` qui aurait capturé une liste au
lieu de relire `hass.data[DOMAIN]` à chaque appel.

- [ ] **Step 2: Déplacer les trois symboles**

`RUN_NOW_SCHEMA` (229-231), `_async_register_services` (955-986) et
`_async_unregister_services` (988-993). La fermeture `_schedulers()` et le
garde-fou `has_service` sont repris tels quels.

- [ ] **Step 3: Mettre à jour `__init__.py`**

`from .services import _async_register_services, _async_unregister_services`.
`RUN_NOW_SCHEMA` n'est utilisé que dans `services.py` : ne pas l'importer, la
porte B le signalerait.

- [ ] **Step 4: Portes A et B**

Expected: porte A code 0, `services` chargé ; porte B inchangée. `vol` ne doit
plus être importé par `__init__.py` si `CONFIG_SCHEMA` n'en a pas besoin — se
fier au constat F401 plutôt qu'à la lecture.

- [ ] **Step 5: Commit, puis porte C**

```bash
git add custom_components/shutters_management/services.py custom_components/shutters_management/__init__.py tests/test_init.py
git commit -m "refactor: extrait les services dans services.py"
git push
```

---

### Task 8: `frontend.py`

**Files:**
- Create: `custom_components/shutters_management/frontend.py`
- Modify: `custom_components/shutters_management/__init__.py`
- Test: `tests/test_frontend.py` (créer)

**Interfaces:**
- Consumes: `DOMAIN` de `.const`.
- Produces: `_async_register_frontend_resources(hass) -> None`, consommé par `__init__.py`.

- [ ] **Step 1: Écrire le test en échec de l'idempotence**

```python
async def test_frontend_resources_are_registered_once(hass: HomeAssistant) -> None:
    """Un second appel sort sur le drapeau sans réenregistrer la carte."""
    with patch(
        "homeassistant.components.frontend.add_extra_js_url"
    ) as add_js, patch.object(
        hass.http, "async_register_static_paths"
    ) as static:
        await _async_register_frontend_resources(hass)
        await _async_register_frontend_resources(hass)

    add_js.assert_called_once()
    static.assert_called_once()
```

Importer depuis `custom_components.shutters_management.frontend`. La fonction
importe `add_extra_js_url` à l'intérieur de son corps : la cible du `patch`
est donc le module d'origine, `homeassistant.components.frontend`.

- [ ] **Step 2: Déplacer le bloc**

`_FRONTEND_DIR`, `_FRONTEND_URL`, `_CARD_URL`,
`_FRONTEND_REGISTERED_FLAG` (918-921) et
`_async_register_frontend_resources` (924-952). Les imports internes au corps
(`pathlib`, `homeassistant.components.frontend`,
`homeassistant.components.http`) restent internes. `Path(__file__).parent`
continue de désigner le dossier du paquet, `frontend.py` y vivant lui aussi.

Nommer ce module `frontend.py` ne masque pas
`homeassistant.components.frontend` : Python 3 n'utilise que des imports
absolus.

- [ ] **Step 3: Mettre à jour `__init__.py`**

`from .frontend import _async_register_frontend_resources`.

- [ ] **Step 4: Portes A et B**

Expected: porte A code 0, `frontend` chargé ; porte B inchangée.

- [ ] **Step 5: Commit, puis porte C**

```bash
git add custom_components/shutters_management/frontend.py custom_components/shutters_management/__init__.py tests/test_frontend.py
git commit -m "refactor: extrait l'enregistrement du frontend dans frontend.py"
git push
```

---

### Task 9: Surface finale d'`__init__.py` et imports directs des plateformes

**Files:**
- Modify: `custom_components/shutters_management/__init__.py`
- Modify: `custom_components/shutters_management/switch.py:13`, `sensor.py:39`, `binary_sensor.py:19`, `button.py:10`

**Interfaces:**
- Consumes: tous les modules des tâches 2 à 8.
- Produces: `__init__.py` réduit au cycle de vie, avec quatre ré-exports.

- [ ] **Step 1: Vérifier le contenu restant d'`__init__.py`**

Doivent y rester, et rien d'autre : `CONFIG_SCHEMA`, `_LOGGER`,
`_RESIDUAL_DEVICE_MODELS`, `_STATE_STORE_KEY`, `async_setup`,
`async_setup_entry`, `async_unload_entry`, `async_remove_entry`,
`_async_update_listener`, plus le bloc d'imports. Cible : environ 200 lignes.

Run: `grep -n "^def \|^async def \|^class \|^[A-Z_]" custom_components/shutters_management/__init__.py`

- [ ] **Step 2: Faire pointer les plateformes vers les modules**

- `switch.py:13` et `sensor.py:39` : `from . import ShuttersScheduler, ShuttersSunProtectionManager` devient `from .scheduler import ShuttersScheduler` + `from .sun_protection import ShuttersSunProtectionManager`.
- `binary_sensor.py:19` : `from .sun_protection import ShuttersSunProtectionManager`.
- `button.py:10` : `from .scheduler import ShuttersScheduler`.

C'est la seconde règle qui garantit l'acyclicité : plus aucun module ne remonte
vers `__init__.py`.

- [ ] **Step 3: Portes A et B**

Expected: porte A code 0, 16 modules chargés, les quatre ré-exports présents.
Porte B **exactement** les 4 constats de référence : à ce stade un F401
supplémentaire signalerait un import résiduel dans `__init__.py`, et c'est la
seule preuve automatique que le fichier a été allégé proprement.

- [ ] **Step 4: Commit, puis porte C**

```bash
git add custom_components/shutters_management/
git commit -m "refactor: les plateformes importent leurs modules directement"
git push
```

---

### Task 10: Livraison 0.9.28

**Files:**
- Modify: `custom_components/shutters_management/manifest.json` (`version`)
- Modify: `CHANGELOG.md`
- Modify: `README.md` (arborescence)
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: la branche complète, porte C au vert.
- Produces: la pull request prête à relire.

- [ ] **Step 1: Passer `version` à `0.9.28` dans `manifest.json`**

- [ ] **Step 2: Entrée CHANGELOG**

Sous `## [Non publié]`, créer `## [0.9.28] — 2026-11-08` avec une section
`### Modifié — découpage interne, aucun changement de comportement`. Doit
mentionner : les huit modules créés, le fait qu'aucun comportement, entité,
service, message ni état persisté ne change, et la seule conséquence visible —
les lignes de journal portent désormais le nom du sous-module
(`…shutters_management.scheduler`), la configuration `logger:` restant valable
par héritage.

- [ ] **Step 3: Arborescence du README**

Remplacer le commentaire de trois lignes sur `__init__.py` par
`# cycle de vie de l'entree` et insérer, dans l'ordre alphabétique,
`frontend.py`, `migrations.py`, `notifications.py`, `presence.py`,
`scheduler.py`, `services.py`, `sun_protection.py`, chacun avec le libellé
d'objet du tableau « Tailles visées » de la spec. Ajouter les trois fichiers de
tests créés (`test_frontend.py`, `test_presence.py`) à la liste `tests/`.

- [ ] **Step 4: ROADMAP.md**

Ajouter `- **v0.9.28** — découpage de \`__init__.py\` en modules dédiés.` à la
liste des versions livrées, supprimer la section `### T1`, et créer en court
terme un nouvel item pour ce que la spec renvoie explicitement à la feuille de
route : le **découpage interne de `ShuttersSunProtectionManager`** (860 lignes
après T1), en notant que séparer le moteur de décision de la commande des
volets porte un vrai risque de comportement, contrairement à T1.

- [ ] **Step 5: Vérifier les deux portes locales une dernière fois, puis commit**

```bash
git add -A
git commit -m "chore: version 0.9.28, CHANGELOG, README et feuille de route"
git push
```

- [ ] **Step 6: Sortir la pull request du brouillon avec sa preuve**

Run: `git diff main --stat -- tests/` puis
`git diff main -- tests/ | grep "^[-+]" | grep -v "^[-+][-+]"`

La description doit affirmer, chiffres en main : aucune logique de test
existante modifiée ; 18 chaînes de cible `patch()` réécrites ; N tests ajoutés
pour les coutures que le découpage expose (présence en chaîne simple, repli
`person.*`, idempotence du frontend, services après deux rechargements, nom du
logger). Coller le diff filtré des tests comme preuve.

```bash
gh pr ready
```

- [ ] **Step 7: Vérification en production, après fusion et publication**

Installation par HACS, redémarrage, puis : l'intégration charge, les 5
sous-entrées sont présentes, switches et capteurs ont survécu — ce qui teste
aussi la relecture de `.storage`.
