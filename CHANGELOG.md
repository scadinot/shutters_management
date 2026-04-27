# Changelog

Toutes les évolutions notables de cette intégration sont consignées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Non publié]

## [0.2.3] — 2026-04-27

### Ajouté

- `entity_id` stables, indépendants de la langue de Home Assistant pour les nouvelles installations : `sensor.shutters_management_next_opening`, `sensor.shutters_management_next_closing`, `switch.shutters_management_simulation_active`, `button.shutters_management_test_open`, `button.shutters_management_test_close`. Le nom d'affichage reste traduit ; seul l'identifiant technique est figé. Mise en œuvre via `_attr_suggested_object_id` (pattern canonique HA) — les renommages utilisateur via l'UI sont préservés.
- Workflow GitHub Actions `Validate Hassfest.yaml` (push, pull request, cron quotidien).
- Workflow GitHub Actions `Validate HACS.yaml` (push, pull request, cron quotidien).
- Badges CI dans le README (`Tests`, `Hassfest`, `HACS`).
- Trois tests `test_*_entity_id*_is_stable_english` qui vérifient via le registry que les `entity_id` finaux correspondent au slug EN attendu (suite : 36 tests, couverture 84 %).
- Section « Notes de migration » dans le README, avec une note v0.2.3 pour les utilisateurs FR/non-EN existants.

### Modifié

- Bump de la version de l'intégration `0.2.2` → `0.2.3` dans `manifest.json`.
- Manifest réordonné selon les règles hassfest (`domain`, `name`, puis ordre alphabétique).
- Renommage du workflow tests `tests.yml` → `tests.yaml`.
- `ROADMAP.md` recentré sur les évolutions à venir : les sections « Livré » des versions passées sont retirées et l'historique détaillé est délégué au `CHANGELOG.md`.

### Corrigé

- Hassfest : ajout d'un `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)` qui signale explicitement que l'intégration n'accepte pas de YAML.

> **Note de migration** : les installations existantes en français (ou autre langue non-EN) conservent leurs `entity_id` traduits stockés dans le registry — c'est volontaire pour ne pas casser les automations existantes. Pour aligner sur les exemples du README, renommez manuellement chaque entité depuis **Paramètres → Appareils et services → Shutters Management** puis clic sur l'entité → modifier l'`entity_id`.

## [0.2.2] — 2026-04-27

### Ajouté

- Suite de tests unitaires (`tests/`) couvrant le config flow, l'options flow, l'init/unload, la logique du scheduler (next_open/next_close, pause, présence, run_now), les sensors, le switch et les boutons (33 tests, couverture 84 %).
- Workflow CI (`.github/workflows/tests.yml`, renommé en `tests.yaml` en v0.2.3) exécutant `pytest` avec couverture sur Python 3.12 et 3.13 à chaque push `main` et chaque pull request.

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

[Non publié]: https://github.com/scadinot/shutters_management/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/scadinot/shutters_management/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/scadinot/shutters_management/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/scadinot/shutters_management/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/scadinot/shutters_management/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/scadinot/shutters_management/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/scadinot/shutters_management/releases/tag/v0.1.0
