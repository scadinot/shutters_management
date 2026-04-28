# Changelog

Toutes les évolutions notables de cette intégration sont consignées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Non publié]

## [0.3.3] — 2026-04-28

### Modifié

- Bump de la version de l'intégration `0.3.2` → `0.3.3` dans `manifest.json`.
- **Configuration plus compacte** :
  - Les deux sections « Ouverture » et « Fermeture » sont désormais **repliées par défaut** (`collapsed: True`) au lieu d'être ouvertes. Les défauts (`fixed`, `08:00:00`, `21:00:00`, offset `0`) couvrent ~90 % des usages, donc le formulaire tient sur une fraction de la hauteur précédente. Un clic suffit pour déplier la section et personnaliser un déclencheur.
  - Le sélecteur de **jours actifs** passe de `SelectSelectorMode.LIST` (7 lignes empilées verticalement, ~280 px) à `SelectSelectorMode.DROPDOWN` (un seul champ avec les jours sélectionnés affichés en chips, ~50 px). C'est l'idiome utilisé par les intégrations core HA qui gèrent les jours de la semaine (`trafikverket_train`, `trafikverket_ferry`, `workday`).

### Pas de breaking change

Aucune modification du schéma, du payload, des tests, du scheduler, des entités ou des services. Le format de données pour `days` reste une liste de chaînes (`["mon", "tue", ...]`), seul le rendu UI change. Les 44 tests existants passent sans modification.

### Limite connue

HA ne propose pas (encore) de sélecteur **tableau / grille** pour les jours de la semaine. `SelectSelectorMode` n'expose que `DROPDOWN` et `LIST`, et `SelectSelectorConfig` n'a pas d'option de colonnes. Le dropdown multi-select avec chips reste l'alternative compacte la plus propre disponible.

## [0.3.2] — 2026-04-28

### Modifié

- Bump de la version de l'intégration `0.3.1` → `0.3.2` dans `manifest.json`.
- **Configuration : panneau unique** — l'écran « Ajouter une intégration » et l'options flow regroupent désormais tous les champs sur **un seul écran**, avec deux sections repliables « Ouverture » et « Fermeture », affichées ouvertes par défaut. Plus de wizard en 2 étapes. Les champs `time` et `offset` sont visibles ensemble dans chaque section ; les libellés indiquent lequel est utilisé selon le mode (`heure fixe` vs `lever/coucher du soleil`).
- Implémentation via `homeassistant.data_entry_flow.section`, mécanisme natif HA utilisé par 10+ intégrations core.
- `_normalize` aplatit les sous-dictionnaires de sections avant validation, donc le reste du code (scheduler, entités) lit toujours `entry.data[CONF_OPEN_MODE]` etc. sans changement.

### Pas de breaking change

Aucune migration de schéma. Les entries v0.3.1 existantes continuent de fonctionner telles quelles ; en v0.3.1, le second step n'écrivait que `*_time` *ou* `*_offset` selon le mode, donc une entrée sunrise n'a pas de `*_time` (et inversement). Avec le nouveau panneau unique, les champs éventuellement absents de `data` sont simplement pré-remplis avec les valeurs par défaut (`DEFAULT_OPEN_TIME`, `DEFAULT_CLOSE_OFFSET`, etc.) à l'affichage, et le scheduler ignore au runtime celui qui ne correspond pas au mode actif. Le scheduler, les entités, les services et les `entity_id` sont strictement inchangés.

### Pas de réactivité côté UI

L'idéal aurait été que les champs `time` / `offset` apparaissent et disparaissent en fonction du `mode` choisi dans le même panneau. **Cette réactivité n'est pas disponible** dans Home Assistant aujourd'hui (vérifié dans `data_entry_flow.py` et `selector.py` du venv HA 2026.x : aucun mécanisme `depends_on`/`visibility`/`show_if`). Le frontend ne re-rend pas un schéma sur changement d'un champ peer. La solution avec sections reste la plus propre alternative actuellement.

## [0.3.1] — 2026-04-28

### Ajouté

- **Déclencheurs solaires** : chaque événement (ouverture / fermeture) peut désormais être configuré dans l'un des trois modes :
  - `fixed` (défaut, comportement historique) — déclenchement à une heure fixe.
  - `sunrise` — déclenchement au lever du soleil.
  - `sunset` — déclenchement au coucher du soleil.

  Pour les modes solaires, un **décalage signé en minutes** (-360 à +360) peut être appliqué, par exemple `+30` pour 30 minutes après le lever, ou `-15` pour 15 minutes avant le coucher. Le décalage aléatoire (`randomize` / `random_max_minutes`) reste appliqué **en plus** du décalage solaire.
- Étape conditionnelle `triggers` dans le config flow et l'options flow : après avoir choisi les modes en étape 1, l'utilisateur ne voit en étape 2 que les champs pertinents (heure fixe **ou** offset signé) pour chaque événement.
- 4 tests dans `tests/test_sun_trigger.py` :
  - délégation à `get_astral_event_next` avec offset positif (sunrise),
  - offset négatif (sunset -30 min),
  - filtrage des jours inactifs (boucle jusqu'à un jour actif),
  - chemin sunrise dans le config flow saute le champ `open_time`.

### Modifié

- Bump de la version de l'intégration `0.3.0` → `0.3.1` dans `manifest.json`.
- `_build_schema` remplacé par deux helpers : `_build_step1_schema` (tout sauf time/offset) et `_build_triggers_schema` (time XOR offset selon le mode).
- `_make_handler` accepte désormais un paramètre `now` optionnel : `async_track_time_change` passe `now`, `async_track_sunrise/sunset` rappellent sans argument.
- `next_open()` / `next_close()` passent par un nouveau `_next_for(time_key, mode_key, offset_key, default_mode)` qui dispatche selon le mode. La logique solaire (`_next_sun`) boucle sur jusqu'à 8 jours pour atterrir sur un jour actif.

### Pas de changement breaking

Les entries v0.3.0 existantes n'ont pas `CONF_OPEN_MODE` / `CONF_CLOSE_MODE` dans leur `data` ; le code retombe sur `MODE_FIXED` par défaut, donc le comportement reste strictement identique. Aucune migration de schéma n'est nécessaire.

## [0.3.0] — 2026-04-27

### Ajouté

- **Multi-instance** : on peut désormais créer plusieurs entrées indépendantes de l'intégration sous le même domaine (ex. « Bureau », « RDC », « Étage »), chacune avec ses propres volets, horaires, jours actifs et mode absence. Chaque entrée crée son propre device dans Home Assistant et expose ses 5 entités sous ce device.
- Champ « Nom de l'instance » (`CONF_NAME`) requis dans le config flow et dans l'options flow. Sert de titre de l'entrée, de nom du device, et de préfixe pour les `entity_id` générés (par exemple `sensor.bureau_next_opening`, `sensor.rdc_next_opening`).
- `async_migrate_entry` qui passe les entrées v1 pré-existantes en v2 en injectant `CONF_NAME = entry.title` (transparent pour l'utilisateur, aucune action requise).
- 4 tests dans `tests/test_multi_instance.py` : coexistence de deux entrées, isolation de la pause entre instances, signal scopé par `entry_id`, migration v1→v2.

### Modifié

- `SIGNAL_STATE_UPDATE` (constante globale) remplacée par une fabrique `signal_state_update(entry_id)` qui retourne un nom de signal par entry. Les entités d'une instance ne reçoivent plus les notifications de l'autre.
- `DeviceInfo.name` des entités sensor/switch/button est désormais dérivé de `entry.title` au lieu d'être figé sur `"Shutters Management"`.
- `_attr_suggested_object_id` retiré ; avec `_attr_has_entity_name = True` Home Assistant génère lui-même un `entity_id` propre `<platform>.<device_slug>_<entity_slug>`.
- Renommer une instance via l'options flow synchronise désormais le titre de l'entry **et** le nom du device dans le device registry.
- `ConfigFlow.VERSION` passe de `1` à `2`.

### Note importante

> **Les entity_ids des installations existantes restent intacts.** Le `unique_id` (préfixé par `entry.entry_id` depuis v0.2.1) et l'`entity_id` stocké dans le registry sont préservés. Seuls les `entity_id` générés pour les **nouvelles** entrées créées en v0.3.0 utilisent le slug du nom (ex. `bureau`, `rdc`).

> **Services broadcast inchangés** : les services `shutters_management.run_now` / `pause` / `resume` agissent toujours sur **toutes** les instances. Le ciblage par instance via `target` est reporté à v0.3.1.

## [0.2.5] — 2026-04-27

### Ajouté

- Assets de marque embarqués dans `custom_components/shutters_management/brand/` :
  - `icon.png` (256×256) — icône carrée standard.
  - `icon@2x.png` (512×512) — icône haute résolution.
  - `logo.png` (768×256) — logo horizontal « Shutters Management » avec l'icône et le wordmark.
  - `logo@2x.png` (1536×512) — logo haute résolution.

  Depuis Home Assistant 2026.3, le frontend charge directement ces fichiers locaux pour afficher l'icône et le logo de l'intégration sur la page « Ajouter une intégration » et dans « Appareils et services ». Le check `brands` de la validation HACS passe désormais sans nécessiter de PR sur le repo `home-assistant/brands`.

### Modifié

- Bump de la version de l'intégration `0.2.3` → `0.2.5` dans `manifest.json`. La version intermédiaire 0.2.4 a été retirée des releases parce que son tag Git avait été placé sur le mauvais commit, ce qui rendait l'archive `v0.2.4.zip` incohérente ; ses fonctionnalités sont incluses ici.
- **Version minimale de Home Assistant relevée à 2026.3.0** dans `hacs.json` — c'est la première version qui charge les assets de marque embarqués. (Le schéma `manifest.json` des intégrations custom n'accepte pas de champ `homeassistant` ; HACS bloque l'installation sur les versions antérieures avant que le code n'arrive sur disque.)
- Section « Prérequis » du README mise à jour.
- **Options flow simplifié** : l'écran « Configurer » s'ouvre désormais directement sur le formulaire d'édition, sans menu intermédiaire. Les anciennes entrées « Tester : ouvrir maintenant », « Tester : fermer maintenant » et « Mettre la simulation en pause / Reprendre la simulation » sont retirées de l'options flow.

### Supprimé

- `async_step_run_open`, `async_step_run_close`, `async_step_pause_simulation`, `async_step_resume_simulation` dans `config_flow.py` (les actions correspondantes restent disponibles via les boutons `button.shutters_management_test_open` / `test_close` et le switch `switch.shutters_management_simulation_active` exposés depuis la v0.2.1, ainsi que via les services `shutters_management.run_now` / `pause` / `resume`).
- Étape intermédiaire `configure` de l'options flow (fusionnée dans `init`).
- Clés de traduction `options.step.init.menu_options`, `options.step.configure`, `options.abort.action_run`, `options.abort.simulation_paused`, `options.abort.simulation_resumed`.

> **Note de migration HA** : si vous tournez sur une version de Home Assistant antérieure à 2026.3, restez sur la v0.2.3 jusqu'à votre prochaine mise à jour HA. La v0.2.5 ne se chargera pas sur HA &lt; 2026.3.

> **Note** : aucune fonctionnalité n'est perdue par la simplification de l'options flow. Les actions sont toujours déclenchables depuis le dashboard (boutons + switch) et depuis les services Home Assistant.

## [0.2.3] — 2026-04-27

Release essentiellement de documentation et de maintenance autour de la v0.2.2 (qui contient les véritables nouveautés fonctionnelles : tests, CI, `entity_id` stables).

### Ajouté

- `CHANGELOG.md` au format [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) couvrant l'historique de v0.1.0 à v0.2.3.
- Section « Notes de migration » dans le README, regroupant la note v0.2.1 (`binary_sensor` → `switch`) et la note v0.2.2 sur les `entity_id` traduits des installations FR existantes.

### Modifié

- Bump de la version de l'intégration `0.2.2` → `0.2.3` dans `manifest.json`.
- `ROADMAP.md` recentré sur les évolutions à venir : les sections « Livré » des versions passées sont retirées et l'historique détaillé est délégué au `CHANGELOG.md`. Restyle ensuite selon la présentation Motivation / Piste technique inspirée de [voltapeak_loops/ROADMAP](https://github.com/scadinot/voltapeak_loops/blob/main/ROADMAP.md).
- Synchronisation du README : structure du dépôt mise à jour, références `tests.yml` corrigées en `tests.yaml`, mention des workflows additionnels.

### Pas de changement fonctionnel

Aucun changement de code dans l'intégration. Seules les méta-données (`manifest.json`) et la documentation (`README.md`, `ROADMAP.md`, `CHANGELOG.md`) évoluent. Compatibilité strictement identique à v0.2.2.

## [0.2.2] — 2026-04-27

### Ajouté

#### Tests et CI

- Suite de tests unitaires (`tests/`) couvrant le config flow, l'options flow, l'init/unload, la logique du scheduler (next_open/next_close, pause, présence, run_now), les sensors, le switch et les boutons. **36 tests, couverture 84 %**.
- Workflow GitHub Actions `.github/workflows/tests.yaml` exécutant `pytest` avec couverture sur Python 3.12 et 3.13 à chaque push `main` et chaque pull request.
- Workflow GitHub Actions `.github/workflows/Validate Hassfest.yaml` (push, pull request, cron quotidien).
- Workflow GitHub Actions `.github/workflows/Validate HACS.yaml` (push, pull request, cron quotidien).
- Badges CI dans le README : `Tests`, `Hassfest`, `HACS`.

#### `entity_id` stables

- Identifiants techniques EN figés pour les nouvelles installations : `sensor.shutters_management_next_opening`, `sensor.shutters_management_next_closing`, `switch.shutters_management_simulation_active`, `button.shutters_management_test_open`, `button.shutters_management_test_close`. Le nom d'affichage reste traduit. Mise en œuvre via `_attr_suggested_object_id` (pattern canonique HA) — les renommages utilisateur via l'UI sont préservés.
- Trois tests `test_*_entity_id*_is_stable_english` qui vérifient via le registry que les `entity_id` finaux correspondent au slug EN attendu.

### Modifié

- Manifest `manifest.json` réordonné selon les règles hassfest (`domain`, `name`, puis ordre alphabétique).

### Corrigé

- Hassfest : ajout d'un `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)` qui signale explicitement que l'intégration n'accepte pas de configuration YAML.

> **Note de migration** : les installations existantes en français (ou autre langue non-EN) conservent leurs `entity_id` traduits stockés dans le registry — c'est volontaire pour ne pas casser les automations existantes. Pour aligner sur les exemples du README, renommez manuellement chaque entité depuis **Paramètres → Appareils et services → Shutters Management** puis clic sur l'entité → modifier l'`entity_id`.

## [0.2.1] — 2026-04-27

### Ajouté

- `switch.shutters_management_simulation_active` : basculable, expose et contrôle l'état actif/pause de la simulation depuis le dashboard.
- `button.shutters_management_test_open` : déclenche immédiatement une ouverture des volets configurés.
- `button.shutters_management_test_close` : déclenche immédiatement une fermeture.

### Supprimé

- `binary_sensor.shutters_management_simulation_active` (remplacé par le switch).

### Breaking change

- Le `binary_sensor.shutters_management_simulation_active` introduit en v0.2.0 a été remplacé par le `switch.shutters_management_simulation_active`. Les automations existantes doivent être mises à jour pour pointer vers le switch (les états restent `on` / `off`). Selon votre registre des entités, l'ancien `binary_sensor` peut rester présent comme entité obsolète ou indisponible après la mise à jour ; vous pouvez le supprimer manuellement du registre.

## [0.2.0] — 2026-04-26

### Ajouté

- Service `shutters_management.run_now` (champ obligatoire `action` : `open` ou `close`) pour forcer un déclenchement immédiat.
- Services `shutters_management.pause` et `shutters_management.resume` pour suspendre temporairement la simulation.
- `sensor.shutters_management_next_opening` : horodatage du prochain déclenchement d'ouverture.
- `sensor.shutters_management_next_closing` : horodatage du prochain déclenchement de fermeture.
- `binary_sensor.shutters_management_simulation_active` : état actif / en pause de la simulation.
- Menu d'options avec entrées « Tester ouverture / fermeture » et « Mettre en pause / Reprendre ».
- Étape de confirmation dans le config_flow si `only_when_away` est coché alors qu'aucune `person.*` ni `presence_entity` n'est disponible.

## [0.1.1] — 2026-04-26

### Corrigé

- Erreur 500 lors de la réouverture de l'options flow.

## [0.1.0] — 2026-04-25

### Ajouté

- Configuration entièrement par interface graphique (`config_flow` + `OptionsFlow`).
- Sélection multiple d'entités `cover.*` pilotées simultanément.
- Heures d'ouverture et de fermeture indépendantes, en heure locale.
- Choix des jours actifs (lundi – dimanche).
- Décalage aléatoire optionnel, plafonné automatiquement avant minuit pour ne pas déborder sur le jour suivant.
- Mode « uniquement en absence » avec entité de présence explicite ou repli automatique sur l'ensemble des `person.*` du système.
- Ré-évaluation des conditions au moment exact de l'exécution différée.
- Annulation propre des déclencheurs et des callbacks différés au déchargement / rechargement.
- Traductions français et anglais.

[Non publié]: https://github.com/scadinot/shutters_management/compare/v0.3.3...HEAD
[0.3.3]: https://github.com/scadinot/shutters_management/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/scadinot/shutters_management/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/scadinot/shutters_management/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/scadinot/shutters_management/compare/v0.2.5...v0.3.0
[0.2.5]: https://github.com/scadinot/shutters_management/compare/v0.2.3...v0.2.5
[0.2.3]: https://github.com/scadinot/shutters_management/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/scadinot/shutters_management/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/scadinot/shutters_management/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/scadinot/shutters_management/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/scadinot/shutters_management/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/scadinot/shutters_management/releases/tag/v0.1.0
