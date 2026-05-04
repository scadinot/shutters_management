# Changelog

Toutes les évolutions notables de cette intégration sont consignées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Non publié]

## [0.6.3] — 2026-05-04

### Modifié — UX des formulaires

Tous les réglages des formulaires de configuration sont désormais
regroupés dans des **panneaux repliés par défaut**, pour réduire
l'encombrement visuel et harmoniser la présentation entre les
différents types de configuration.

- **Hub** : les panneaux **Notifications push** et **Annonce vocale**
  sont désormais repliés par défaut (comme **Capteurs de protection
  solaire** déjà l'était).
- **Planification** : nouveau panneau replié **Jours actifs**.
- **Simulation de présence** : nouveaux panneaux repliés **Jours
  actifs**, **Décalage aléatoire** et **Conditions de présence**.
- **Protection solaire** : nouveaux panneaux repliés **Orientation et
  exposition**, **Seuils de déclenchement** et **Capteur intérieur**.

Aucune migration de données : seul le rendu du formulaire change, les
données stockées dans les sous-entrées restent inchangées.

## [0.6.2] — 2026-05-04

### Corrigé

- Erreur de validation **« Entity is neither a valid entity ID nor a
  valid UUID »** lors de la soumission du formulaire du hub quand un
  champ capteur optionnel (lux, UV, température extérieure) est laissé
  vide. La même correction est appliquée aux champs `temp_indoor_entity`
  (groupe Protection solaire), `presence_entity` (Simulation de
  présence) et `tts_engine` (Annonce vocale).

### Modifié

- Libellés des champs **Capteur de luminosité extérieure** et
  **Capteur d'indice UV** dans les paramètres du hub : formulation
  plus claire indiquant qu'ils sont optionnels et expliquant leur
  rôle (utilisé seul, en repli ou en complément).

## [0.6.1] — 2026-05-04

### Ajouté — entités de diagnostic pour Sun Protection

Chaque groupe **Protection solaire** expose désormais 15 nouvelles
entités classées sous **Diagnostic** (masquées par défaut sur les
dashboards, accessibles dans les cards et automatisations) qui
explicitent le moteur de décision et aident à calibrer les seuils.

**Suivi du calcul (4 sensors)** :

- `sensor.{groupe}_sun_protection_status` — statut traduit (`enum` :
  Désactivé, Override manuel, Aucun capteur, Soleil sous l'horizon,
  Hors arc, Trop froid dehors, Lux trop bas, UV trop bas, Pièce trop
  fraîche, Fermeture en attente, Actif).
- `sensor.{groupe}_sun_protection_lux_threshold` — seuil lux adaptatif
  effectif selon la T_ext (35 000 / 50 000 / 70 000 lux), `unknown`
  quand pas de gate lux.
- `sensor.{groupe}_sun_protection_pending_seconds` — secondes restantes
  dans le debounce close (10 min) ou open (20 min). `0` hors fenêtre.
- `sensor.{groupe}_sun_protection_override_until` (`timestamp`) —
  prochain reset 04:00 quand l'override manuel est armé.

**Lectures contextualisées par groupe (6 sensors)** :

- `sensor.{groupe}_sun_protection_sun_azimuth` (°) — azimut sun.sun.
- `sensor.{groupe}_sun_protection_sun_elevation` (°) — élévation sun.sun.
- `sensor.{groupe}_sun_protection_lux` (lx, `illuminance`) — relais du
  capteur lux configuré au hub.
- `sensor.{groupe}_sun_protection_uv_index` — relais UV.
- `sensor.{groupe}_sun_protection_temp_outdoor` (°C, `temperature`).
- `sensor.{groupe}_sun_protection_temp_indoor` (°C, `temperature`).

**Écarts dérivés pour calibrer (4 sensors)** :

- `sensor.{groupe}_sun_protection_azimuth_diff` (°) —
  `|azimuth − orientation|`.
- `sensor.{groupe}_sun_protection_elevation_margin` (°) —
  `elevation − min_elevation` (négatif → soleil trop bas).
- `sensor.{groupe}_sun_protection_lux_margin` (lx) —
  `lux − seuil_courant`.
- `sensor.{groupe}_sun_protection_uv_margin` —
  `uv − min_uv`.

**Indicateur géométrique pur (1 binary_sensor)** :

- `binary_sensor.{groupe}_sun_facing` — `on` quand
  `azimuth ∈ [orientation ± arc]` ET `elevation ≥ min_elevation`,
  indépendamment de lux/UV/temp/override/switch. Aide à valider
  l'arc et le seuil d'élévation.

### Tests

- Nouveau `tests/test_sun_protection_entities.py` (15 cas) couvrant
  les 6 propriétés diagnostic du manager
  (`azimuth`, `elevation`, `azimuth_diff`, `is_sun_facing`,
  `lux_close_threshold`, `pending_seconds`) ainsi que l'état
  superficiel des 14 sensors + 1 binary_sensor.
- Suite complète : 179 tests verts.

## [0.6.0] — 2026-05-04

### Refonte de la protection solaire

L'algorithme de protection solaire passe d'un simple test
**élévation + azimut + UV** à une logique combinée
**lux + UV + température extérieure + température pièce** avec
hystérésis, debounce et respect d'un override manuel. Le but : ne plus
fermer inutilement en mi-saison ou ciel couvert, ne plus rouvrir au
moindre nuage, et respecter les actions manuelles de l'utilisateur
jusqu'au lendemain matin.

### Modifié — schéma & configuration

- **Hub** : nouveaux capteurs (tous optionnels) regroupés dans une
  section repliable « Capteurs de protection solaire » :
  - `lux_entity` — capteur de luminosité extérieure (lux), capteur
    *primaire* de l'algorithme.
  - `uv_entity` — capteur d'indice UV (conservé depuis v0.5.x),
    *alternative* ou *complément additif* au lux.
  - `temp_outdoor_entity` — capteur de température extérieure (°C).
- **sun_protection** (par groupe) :
  - `min_uv` (conservé depuis v0.5.x) — utilisé seulement si un
    capteur UV est configuré au hub.
  - Nouveau champ optionnel `temp_indoor_entity` — capteur de
    température de la pièce ciblée. Sans ce capteur, le critère de
    température pièce est sauté.

### Quatre modes d'activation au choix

| Capteurs configurés | Comportement |
|---------------------|--------------|
| **lux seul** | Seuils lux adaptatifs (T_ext) + debounce 10/20 min. |
| **UV seul** | `uv ≥ min_uv` (sans debounce — l'UV évolue lentement). |
| **lux + UV** | **Les deux** doivent être satisfaits (défense en profondeur). |
| **rien** | Feature désactivée (status `no_sensor`). |

### Ajouté — logique d'activation

- **Table de seuils adaptatifs lux** (codée en dur) :
  - `T_ext < 20 °C` → jamais de fermeture (gain solaire bienvenu).
  - `20 ≤ T_ext < 24` → ferme dès `lux ≥ 70 000` ET `T_pièce ≥ 24 °C`.
  - `24 ≤ T_ext < 30` → ferme dès `lux ≥ 50 000` ET `T_pièce ≥ 23 °C`.
  - `T_ext ≥ 30` (canicule) → ferme dès `lux ≥ 35 000`, `T_pièce`
    ignorée (pré-protection).
  - Sans capteur `T_ext`, on retombe sur le seuil standard 50 000.
- **Hystérésis** : la réouverture utilise des seuils plus larges que
  la fermeture pour éviter le yoyo aux limites. Arc + 15°, élévation
  - 5°, lux de réouverture 25 000.
- **Debouncing** (lux uniquement) : le lux doit dépasser le seuil
  pendant **10 minutes** pour fermer (absorbe les éclats de soleil),
  et descendre sous le seuil de réouverture pendant **20 minutes**
  pour rouvrir (absorbe les nuages qui passent).
- **Override manuel** : si l'utilisateur déplace un volet à la main
  pendant le mode soleil, l'automatisme s'arrête pour cette façade
  jusqu'à **04:00 le lendemain**. Programmé via `async_track_time_change`.

### Ajouté — attributs binary_sensor

`binary_sensor.{groupe}_sun_protection_active` expose désormais :

- `lux`, `uv_index`, `temp_outdoor`, `temp_indoor` — valeurs lues à
  l'instant T (`null` si capteur absent).
- `override_until` — ISO 8601 du prochain reset, ou `null`.
- `status` enrichi : `disabled`, `override`, `no_sensor`,
  `below_horizon`, `out_of_arc`, `temp_too_cold`, `lux_too_low`,
  `uv_too_low`, `room_too_cool`, `pending_close`, `active`.

### Migration v5 → v6 — additive (zéro perte)

- **Aucune purge** : `uv_entity` (hub) et `min_uv` (sun_protection)
  restent intacts. Les installations existantes basées sur l'UV
  continuent de fonctionner sans modification.
- Les nouveaux capteurs (`lux_entity`, `temp_outdoor_entity`,
  `temp_indoor_entity`) restent absents jusqu'à ce que l'utilisateur
  les configure via **Paramètres → Appareils et services → Shutters
  Management → Configurer** (et reconfigure du groupe pour T_pièce).
- Migration purement de version (5 → 6) sans réécriture de schéma.

### Tests

- Réécriture étendue de `tests/test_sun_protection.py` (28 cas) :
  helpers de seuils, gates d'activation, table adaptative,
  hystérésis arc/élévation, debounce close/open, **gate UV
  (seul / combiné / drop pendant sun mode)**, override + reset
  04:00, switch enable/disable, no_sensor.
- Nouveau `test_migration_v5_to_v6_preserves_uv` dans
  `tests/test_migration.py`.

## [0.5.8] — 2026-05-03

### Corrigé

- **Suite de la v0.5.7** : la chaîne vide `""` utilisée pour masquer le label
  redondant du sélecteur d'entités provoquait un fallback côté frontend HA,
  qui ré-affichait alors la clé brute « covers ». Le label interne devient
  désormais « Sélection » (FR) / « Selection » (EN), distinct du titre de la
  section « Volets à piloter » / « Shutters to control » et donc non
  redondant. (Une tentative intermédiaire avec un espace insécable a été
  rejetée par Hassfest qui interdit les chaînes vides ou composées
  uniquement d'espaces.)

## [0.5.7] — 2026-05-03

### Corrigé

- **Label « Volets à piloter » dupliqué** dans la section repliable des
  Planifications, Simulations de présence et Protections solaires. Le titre
  de la section et le label du champ sélecteur d'entités étaient identiques,
  rendant le second redondant. Le label interne du champ est désormais vide
  côté FR/EN ; seul le titre de la section reste affiché.

## [0.5.6] — 2026-05-03

### Changé

- **Volets à piloter dans une section repliable** (Planification, Simulation
  de présence et Protection solaire). Le sélecteur multi-entités est désormais
  encapsulé dans un groupe « Volets à piloter » (FR) / « Shutters to control »
  (EN), identique aux groupes Ouverture et Fermeture.

## [0.5.5] — 2026-05-03

### Changé

- **Boutons d'action renommés.** « Tester l'ouverture / la fermeture »
  deviennent « Ouverture / Fermeture » (FR) et « Test open / Test close »
  deviennent « Opening / Closing » (EN). Reflète leur usage légitime dans des
  automatisations (`button.press`).
- Pour les nouvelles installations, l'entity_id passe de
  `button.<nom>_test_open` / `_test_close` à `button.<nom>_open` / `_close`.
- **Compatibilité préservée** : le `unique_id` interne reste identique. Les
  installations existantes conservent leur entity_id (`_test_open` /
  `_test_close`) et leurs automatisations continuent de fonctionner sans
  changement.

## [0.5.4] — 2026-05-03

### Ajouté

- **Mode « Sans » pour les déclencheurs Ouverture et Fermeture** (Planification
  et Simulation de présence). Sélectionner « Sans » pour un sens désactive
  entièrement ce déclencheur : le volet s'ouvre (ou se ferme) uniquement via
  l'autre sens, sans déclenchement automatique opposé.
  - Nouveau mode interne `none` dans `TRIGGER_MODES`.
  - Quand `mode = none`, aucun `async_track_*` n'est enregistré.
  - `next_open()` / `next_close()` retournent `None` → capteur en état `unknown`.
  - Le mode apparaît en premier dans le dropdown : **Sans** / Heure fixe /
    Lever du soleil / Coucher du soleil.

## [0.5.3] — 2026-05-03

### Supprimé

- **Code mort post-`single_config_entry`** : depuis v0.5.2, HA core
  intercepte toutes les tentatives de second flow hub avant d'atteindre
  `async_step_user` (`config_entries.py:1460`). En conséquence :
  - `_abort_if_unique_id_configured()` retiré de `async_step_user`
    (jamais déclenché en présence d'une entrée existante).
  - Clé `config.abort.already_configured` retirée de `strings.json`,
    `translations/fr.json` et `translations/en.json` (jamais affichée).

Les `config_subentries.*.abort.already_configured` (détection de noms
dupliqués sur les sous-entrées Planification, Simulation de présence et
Protection solaire) sont conservés — toujours actifs.

## [0.5.2] — 2026-05-03

### Corrigé

- **`single_config_entry` déplacé dans `manifest.json`** : le frontend HA
  ne lit ce flag que depuis le manifest (`loader.py:455`), jamais sur la
  classe `ConfigFlow`. L'attribut de classe ajouté en v0.5.1 était sans
  effet et a été retiré. Désormais, cliquer sur « Ajouter un pont »
  alors qu'un hub existe déjà déclenche le dialogue HA standard
  *« Cette intégration n'autorise qu'une seule configuration »* (au lieu
  de notre message `already_configured` custom).

### Note

Le bouton « Ajouter un pont » **reste visible** sur la page de détail de
l'intégration : c'est le comportement standard de HA pour les intégrations
de type `hub`. `single_config_entry` ne masque pas le bouton, il rend le
flow non fonctionnel et affiche un message localisé au clic.

## [0.5.1] — 2026-05-03

### Corrigé

- **Bouton « Ajouter un pont » masqué** quand l'intégration est déjà
  configurée : `single_config_entry = True` est désormais déclaré sur le
  `ConfigFlow` du hub. Il devenait inutile (et trompeur) puisque l'unique
  hub est créé au premier setup.
- Message d'abandon `already_configured` mis à jour pour refléter les trois
  types de sous-entrée (Planification, Simulation de présence, Protection
  solaire) au lieu de mentionner uniquement « instance ».

## [0.5.0] — 2026-05-02

### Ajouté

- **Nouveau type de sous-entrée « Simulation de présence »** (clé interne
  `presence_simulation`). Trois types de groupe sont désormais proposés via
  « Ajouter un service » : **Planification**, **Simulation de présence**,
  **Protection solaire**.
- La Simulation de présence reprend le formulaire de Planification et y
  ajoute les quatre champs dédiés à la simulation : `randomize`,
  `random_max_minutes`, `only_when_away`, `presence_entity`.

### Modifié

- **Planification (sous-entrée `instance`)** : les champs `randomize`,
  `random_max_minutes`, `only_when_away` et `presence_entity` sont retirés
  du formulaire. La planification redevient strictement déterministe.
- Libellés : « Planning de présence » → **« Planification »** (FR) /
  « Presence schedule » → **« Schedule »** (EN). Le switch « Simulation
  active » devient simplement **« Activé »** / **« Enabled »** (la clé de
  traduction `simulation_active` reste inchangée pour ne pas casser les
  `entity_id` existants).
- Le scheduler ignore désormais `randomize` / `only_when_away` /
  `presence_entity` pour les sous-entrées `instance`, même si ces clés
  subsistent dans `subentry.data`.

### Migration (v4 → v5)

- Toutes les sous-entrées `instance` existantes deviennent des
  Planifications. Les quatre champs de simulation sont **purgés** de leur
  `data` lors du chargement. Pour retrouver le comportement d'avant
  (aléa / condition d'absence), créer une sous-entrée
  **« Simulation de présence »**.
- Les `entity_id` (`switch.{...}_simulation_active`,
  `sensor.{...}_next_open`, `sensor.{...}_next_close`,
  `button.{...}_test_open`, `button.{...}_test_close`) sont conservés.

## [0.4.11] — 2026-05-02

### Corrigé

- **Sous-titre du device** : nettoyage du champ `model` résiduel (« Presence
  schedule » / « Sun protection ») persisté dans le device registry HA depuis
  les v0.4.8/v0.4.9. La v0.4.10 avait supprimé ce champ du code mais HA ne
  nettoyait pas la valeur en cache lors d'un simple reload.
- Migration ajoutée dans `async_setup_entry` : à chaque chargement, les
  devices liés au hub voient leur `model` mis à `None` via
  `device_registry.async_update_device(device.id, model=None)`. La migration
  est idempotente (skip si déjà à `None`).

> Pour les installs sur v0.4.10 : la mise à jour vers v0.4.11 nettoie
> automatiquement le sous-titre au prochain redémarrage / reload.

## [0.4.10] — 2026-05-02

### Modifié

- **Nom du device traduit par type** (FR/EN), via `translation_key` sur
  `DeviceInfo` et nouvelle section `device` dans `strings.json` /
  `translations/{en,fr}.json` :
  - Sous-entrée `instance` → « Planning de présence » (FR) / « Presence
    schedule » (EN)
  - Sous-entrée `sun_protection` → « Protection solaire » (FR) / « Sun
    protection » (EN)
- **Suppression du champ `model`** (`Presence schedule` / `Sun protection`),
  devenu redondant avec le nom traduit. Le champ n'était de toute façon pas
  traduit par HA.
- **Suppression de `name=subentry.title`** dans les `DeviceInfo` (écrasé par
  `translation_key` côté HA — code mort). Le nom de la pièce reste affiché
  par la carte parente (subentry).

### Supprimé

- Constantes `DEVICE_MODEL_INSTANCE` et `DEVICE_MODEL_SUN_PROTECTION` dans
  `const.py`.

> **Note** : pour les installations existantes, recharger l'intégration
> (`Settings > Devices > Shutters Management > … > Reload`) pour que HA
> recalcule le nom du device avec la nouvelle traduction.

## [0.4.9] — 2026-05-02

### Corrigé

- **Nom du device sur la carte** : restauration au titre de la sous-entrée
  (« Bureau », « Chambres », « Séjour ») au lieu de la clé brute « instance »
  ou « sun_protection » qui s'affichait depuis la v0.4.7.
- Cause racine : `translation_key` avait été ajouté sur `DeviceInfo` pour une
  tentative d'icône via `icons.json`, mécanisme non supporté par HA. Sans
  traduction correspondante dans `strings.json`, HA tombait en fallback sur
  la clé brute, ce qui écrasait le `name=subentry.title`. Référence :
  `homeassistant/helpers/device_registry.py:871-881`
  (`translations.get(full_translation_key, translation_key)`).
- Le champ `model` ajouté en v0.4.8 (« Presence schedule » / « Sun protection »)
  reste en place et continue de différencier les deux familles de devices.

> **Note** : pour les installations existantes, recharger l'intégration
> (`Settings > Devices > Shutters Management > … > Reload`) pour que HA
> recalcule le nom du device depuis `DeviceInfo`.

## [0.4.8] — 2026-05-02

### Ajouté

- **Champ `model` sur les devices** pour différencier visuellement les deux
  familles de sous-entrées dans la fiche détaillée HA :
  - Sous-entrée `instance` → `model = "Presence schedule"`
  - Sous-entrée `sun_protection` → `model = "Sun protection"`
  - Libellés en anglais car `DeviceInfo.model` n'est pas traduit par HA.
  - Centralisés dans `const.py` (`DEVICE_MODEL_INSTANCE`,
    `DEVICE_MODEL_SUN_PROTECTION`) pour éviter les divergences entre
    plateformes (switch, sensor, button, binary_sensor).
- C'est le pattern utilisé par toutes les intégrations natives (Shelly,
  TP-Link, ZHA, Z-Wave JS, MQTT) pour distinguer plusieurs types de devices
  d'une même intégration.

> **Limitation HA documentée** : l'icône du device card dans la liste de
> l'intégration ne peut pas être personnalisée par device pour un
> `DeviceEntryType.SERVICE`. Aucune section `device` dans `icons.json`,
> aucun champ `icon` sur `DeviceInfo` — vérifié sur HA 2026.x et 100+
> intégrations natives. Le champ `model` est le seul levier officiel.

## [0.4.7] — 2026-05-02

### Ajouté

- **Icônes MDI** par entité via `icons.json` : chaque entité affiche
  désormais une icône distinctive dans le tableau de bord et les listes
  d'entités HA.
  - Switch simulation active → `mdi:calendar-clock`
  - Switch protection solaire → `mdi:weather-sunny`
  - Binary sensor protection solaire active → `mdi:sun-angle`
  - Sensor prochaine ouverture → `mdi:blinds-open`
  - Sensor prochaine fermeture → `mdi:blinds`
  - Bouton tester ouverture → `mdi:arrow-up-circle-outline`
  - Bouton tester fermeture → `mdi:arrow-down-circle-outline`
- `translation_key` sur chaque `DeviceInfo` (`"instance"` /
  `"sun_protection"`) pour préparer les noms de devices traduits dans
  les futures versions de HA.

> **Note** : les sections `device` et `services` d'`icons.json` ne sont
> pas acceptées par hassfest dans la version HA actuelle — seule la
> section `entity` est prise en charge. Les icônes des device cards de la
> vue intégration restent donc génériques.

## [0.4.6] — 2026-05-02

### Ajouté

- **Protection solaire par orientation** — nouveau type de sous-entrée
  `sun_protection` à créer depuis le hub :
  - Orientation (8 cardinaux N/NE/E/SE/S/SO/O/NO), arc d'exposition
    (±°), élévation solaire minimale, indice UV minimum, position cible.
  - Abaisse les volets exposés automatiquement quand le soleil fait face à
    l'orientation configurée.
  - Restauration automatique de la position d'origine à la sortie du mode
    soleil (sauf mouvement manuel détecté).
  - Le scheduler de présence **gagne toujours** en cas de conflit.
  - S'applique en permanence (indépendant de la détection de présence).
- **Capteur UV optionnel** au niveau du hub (`uv_entity`) : si renseigné,
  l'activation du groupe n'a lieu qu'au-dessus du seuil UV configuré.
- Deux nouvelles entités par groupe de protection solaire :
  - `switch.<groupe>` — activer/désactiver le groupe
  - `binary_sensor.<groupe>_active` — vrai quand les volets sont en mode
    soleil (attributs : élévation, azimut, UV, statut)
- Plateforme `binary_sensor` ajoutée à l'intégration.

### Correctifs

- Clés du sélecteur d'orientation en minuscules (`n/ne/e/…`) pour
  satisfaire la règle hassfest `[a-z0-9-_]+`.
- `entity_id` dérivé de la `translation_key` anglaise (stable quel que
  soit la locale active à l'installation).
- Snapshots protégés contre les positions intermédiaires émises par HA
  pendant le mouvement d'un volet vers la position commandée.

### Tests

- Nouvelle suite `tests/test_sun_protection.py` (10 tests).
- Couverture du config flow étendue aux groupes `sun_protection`
  (création, erreurs de validation, reconfiguration, persistance de
  `uv_entity`).

## [0.4.5] — 2026-05-01

### Modifié

- **Sélecteur radio « Quand envoyer »** (3 boutons) à la place des
  cases à cocher `notify_when_away_only` / `tts_when_away_only` :
  chaque section de canal expose désormais un seul sélecteur avec les
  options **Sans / Toujours / Absence uniquement**, traduit en FR et EN.
  - **Sans** : canal désactivé (même si des services/enceintes sont
    renseignés).
  - **Toujours** : envoi après chaque action d'ouverture ou fermeture.
  - **Absence uniquement** : envoi seulement quand la présence est
    détectée absente.
- **Panneau hub en 2 sections autonomes** (suppression de la section
  intermédiaire « Notifier uniquement en mode absence »). Chaque
  canal est désormais auto-suffisant :
  - **Notifications push** : `notify_services` + sélecteur de mode.
  - **Annonce vocale** : `tts_engine`, `tts_targets` + sélecteur de
    mode.
- **Libellés raccourcis** et options flow renommé en
  « Paramètres du hub ».

### Schéma — migration v3 → v4

- Les booléens `notify_when_away_only` et `tts_when_away_only` sont
  remplacés par `notify_mode` et `tts_mode` (valeurs : `disabled` /
  `always` / `away_only`).
- `async_migrate_entry` fait la conversion automatiquement au
  premier démarrage après la mise à jour : si les services push
  étaient vides → `disabled` ; si `notify_when_away_only=True` →
  `away_only` ; sinon → `always`.  Identique côté TTS.
- `config_flow.py` passe à `VERSION = 4`.

### Tests

- Réécriture des helpers `_setup_hub` / `_setup_tts_hub` avec les
  nouveaux paramètres `notify_mode` / `tts_mode`.
- Nouveau test `test_no_notification_when_mode_disabled` et
  `test_no_tts_when_mode_disabled`.
- `test_migration_v3_to_v4_converts_boolean_flags` remplace le
  précédent test « noop » de la v3.
- Suite complète : **90 tests verts**.

## [0.4.4] — 2026-05-01

### Modifié

- **Réorganisation du panneau hub** en 3 sections HA repliables, dans
  l'ordre demandé par les utilisateurs :
  1. **Notifier uniquement en mode absence** : les deux toggles
     existants (`notify_when_away_only` et `tts_when_away_only`)
     groupés visuellement, libellés cette fois comme « Appliquer aux
     services de notification » et « Appliquer aux annonces vocales ».
  2. **Services de notification** : champ `notify_services`.
  3. **Annonce vocale** : champs `tts_engine` et `tts_targets`.
- Le toggle `sequential_covers` reste au top-level (au-dessus des
  sections), car il configure le scheduler et non le canal de notif.
- L'options flow du hub présente la même structure pour rester
  cohérent.
- **Données stockées inchangées** : `_normalize_hub` aplatit les
  sections après soumission, `entry.data` garde sa structure plate
  v0.4.3 (clés `notify_services`, `notify_when_away_only`, etc.). Les
  installs existantes continuent donc de marcher tel quel — pas de
  migration de schéma.

### Ajouté

- **Traduction de `reconfigure_successful`** : après l'édition d'une
  instance via le bouton « Modifier », HA affiche désormais
  « Configuration mise à jour. » (FR) ou « Configuration updated. »
  (EN) au lieu de la clé technique brute. Couvert par
  `config_subentries.instance.abort.reconfigure_successful` dans
  `strings.json` + `translations/{en,fr}.json`.

### Tests

- Adaptation des deux tests `test_hub_user_flow_creates_singleton` et
  `test_hub_options_flow_updates_notification_settings` pour soumettre
  un `user_input` imbriqué par section (le flatten fait par
  `_normalize_hub` est testé indirectement via les assertions sur
  `entry.data`, qui reste plate).
- Suite complète : **88 tests verts**.

## [0.4.3] — 2026-05-01

### Ajouté

- **Annonces vocales sur enceintes connectées** (Google Home, Nest,
  Sonos, …) en complément des notifications push. Trois nouveaux
  champs au niveau du hub :
  - **« Moteur d'annonce vocale (TTS) »** : sélection d'une entité
    `tts.*` (le provider TTS, ex. `tts.cloud`, `tts.google_translate_en_com`).
  - **« Enceintes connectées pour les annonces »** : multi-select
    d'entités `media_player.*`.
  - **« Annoncer uniquement en absence »** : toggle dédié, **indépendant**
    du toggle équivalent côté push notifications.
- Quand le moteur TTS et au moins une enceinte sont configurés, chaque
  action open/close déclenche en plus un appel `tts.speak` qui fait
  parler les enceintes en parallèle. Le message est compact, dédié à
  l'oral :
  - FR : `« Volets ouverts : Salon, Cuisine, Chambre. »`
  - EN : `« Shutters opened: Living Room, Kitchen, Bedroom. »`
- Push et TTS sont **strictement indépendants** : un échec d'un canal
  (provider TTS injoignable, enceinte éteinte, notifier cassé)
  n'empêche jamais l'autre canal de partir, ni l'action sur les volets.
- Les deux toggles « away-only » étant séparés, on peut router
  finement — par exemple, push toujours, mais TTS uniquement en
  absence.

### Modifié

- Bump `manifest.json` : `0.4.2` → `0.4.3`.
- `_async_send_notifications` est découpée en deux helpers internes
  (`_async_send_push_notifications` et `_async_send_tts_announcements`)
  pour rendre l'isolation des canaux explicite et évoluable.

### Tests

- Nouveau `tests/test_tts_announcements.py` (11 cas) :
  pas d'appel sans engine, pas d'appel sans targets, message en FR,
  message en EN, action open / close, format compact à virgules
  (jamais de `\n`), toggle away-only TTS qui skip à la maison et
  qui parle en absence, indépendance des deux toggles away-only,
  TTS cassé qui ne bloque pas le cover, scheduler unloaded qui
  silence aussi le TTS.
- Suite complète : **88 tests verts** (77 + 11).

### Pourquoi ce canal séparé

Une notification push est silencieuse et nominative ; une annonce
vocale est ambiante et **immédiate** — on entend depuis n'importe
quelle pièce que les volets bougent. Les deux sont
complémentaires plutôt qu'alternatifs, d'où le découplage complet
(toggles d'absence indépendants, robustesse cross-canal).

## [0.4.2] — 2026-05-01

### Modifié

- **Format des notifications** : le corps du message liste désormais
  **chaque volet sur sa propre ligne**, dans **l'ordre où le scheduler
  les a réellement actionnés** (= ordre du `random.shuffle` en mode
  séquentiel, ordre de la configuration en mode parallèle). Le
  comptage `(N)` est remplacé par cette énumération nominative.
  - Avant (v0.4.1) : `Volets ouverts (3)`
  - Après (v0.4.2) :
    ```
    Volets ouverts :
    Bureau gauche
    Bureau droit
    Bureau fond
    ```
- Chaque volet est rendu via son `friendly_name` (celui que l'on voit
  dans Lovelace), avec fallback sur l'`entity_id` si le state n'est
  pas disponible ou n'expose pas de `friendly_name`. Localisation
  FR/EN inchangée.
- Bump `manifest.json` : `0.4.1` → `0.4.2`.

### Tests

- `tests/test_notifications.py` enrichi : assertion ligne par ligne
  sur le nouveau format, nouveau test
  `test_notification_lists_covers_in_processing_order` qui verrouille
  l'ordre du shuffle dans le body, nouveau test
  `test_notification_falls_back_to_entity_id_without_friendly_name`
  pour le fallback.
- Suite complète : **76 tests verts** (74 + 2).

### Pourquoi ce changement

Une notification « Volets ouverts (3) » indique qu'il s'est passé
quelque chose mais ne dit pas **lesquels** ; sur une instance qui
contrôle 5–6 volets, l'utilisateur préfère savoir que c'est bien
« Salon + Cuisine + Chambre 1 » plutôt qu'un compteur opaque.
L'ordre traité est aussi exposé pour permettre de déboguer un
réseau radio capricieux : si le 3ᵉ volet a un comportement bizarre,
on voit dans la notif qu'il est bien passé en 3ᵉ position.

## [0.4.1] — 2026-05-01

### Ajouté

- **Mode séquentiel + aléatoire** pour l'actionnement des volets, opt-in
  via une nouvelle option **« Actionner les volets l'un après l'autre,
  dans un ordre aléatoire »** dans la configuration du hub
  (« Configurer » sur la device card du hub).
- Quand l'option est activée, à chaque déclenchement (planning,
  `run_now`, boutons « Tester ») la liste des volets est mélangée puis
  parcourue **un par un** : chaque appel `cover.open_cover` /
  `cover.close_cover` est lancé en `blocking=True` puis le scheduler
  attend que le state du volet passe à sa cible (`open` / `closed`)
  avant de passer au suivant.
- **Garde-fou de 90 s** par volet (`COVER_ACTION_TIMEOUT_SECONDS`) :
  un volet qui n'updaterait jamais son state (driver minimaliste,
  panne moteur) ne bloque pas la queue ; un warning est loggé et la
  séquence continue avec le volet suivant.
- Si le scheduler est déchargé en plein milieu d'une séquence
  (suppression de la subentry, redémarrage HA), la queue s'interrompt
  proprement.

### Modifié

- Le mode par défaut **reste l'appel groupé** (1 seul `cover.<service>`
  sur la liste complète, comportement v0.4.0). Aucun comportement
  visible ne change si vous ne touchez pas à la nouvelle option.
- Notifications inchangées : un seul message envoyé à la fin de la
  séquence, jamais un par volet.
- Bump `manifest.json` : `0.4.0` → `0.4.1`.

### Tests

- Nouveau `tests/test_sequential_covers.py` (6 cas) :
  rétrocompatibilité du mode batché, mode séquentiel exécute N appels,
  ordre aléatoire wired up via `random.shuffle`, attente effective du
  state cible, sortie propre sur timeout, target `closed` pour close.
- Suite complète : **74 tests verts**.

### Pourquoi cette option

Le burst parallèle d'origine envoie en quelques millisecondes N
commandes au cluster radio (Z-Wave, Zigbee, RF433). Sur les réseaux
chargés, certaines commandes peuvent se perdre ou être dépriorisées,
laissant un volet en travers. Le mode séquentiel + aléatoire :

1. **Évite la collision réseau** en sérialisant les commandes.
2. **Renforce la simulation de présence** : un humain n'ouvre pas
   tous ses volets simultanément ; l'ordre aléatoire brouille
   davantage les routines détectables depuis l'extérieur.

## [0.4.0] — 2026-05-01

### Refactor majeur — passage au modèle hub + subentries

- **Nouvelle architecture** : l'intégration n'expose plus une `ConfigEntry`
  par planning de volets, mais **une seule entry « hub » singleton** qui
  porte la configuration partagée (services de notification) et regroupe
  chaque planning sous forme de **`ConfigSubentry`** de type `instance`.
- Pattern `ConfigSubentryFlow` (HA ≥ 2025.3, stable depuis 2026.x) — voir
  l'exemple `homeassistant/components/energyid/` qui sert de modèle.
- `manifest.json` : `version` `0.3.5` → `0.4.0`, `integration_type`
  `service` → `hub`.

### Ajouté — notifications partagées

- **Section « Notifications »** dans le config flow et l'options flow du
  hub : multi-select des services `notify.*` à appeler après chaque
  action open/close (suggestions auto-complétées via
  `hass.services.async_services()`, saisie libre acceptée pour les
  notifiers nommés dynamiquement).
- Toggle **« seulement en absence »** (`notify_when_away_only`) : limite
  l'envoi aux situations où la motivation initiale s'applique
  (« quelqu'un — l'intégration — vient d'agir sur la maison »).
- Messages **localisés FR/EN** (`Volets ouverts (N)` / `Shutters closed
  (N)`), titre = nom de la subentry.
- Une notification cassée (notifier mal configuré, intégration tierce
  indisponible) **ne bloque jamais** l'action sur les volets : appel
  cover effectué d'abord, notify avec `blocking=False` ensuite.

### Migration v2 → v3 — automatique et conservatrice

- Au boot (`async_setup`), toutes les entries v0.3.x sont **promues en
  subentries d'un hub auto-créé** :
  1. La 1ʳᵉ entry v2 rencontrée est convertie **en place** en hub
     (`unique_id="_global"`, `data[CONF_TYPE]="hub"`, `version=3`) ;
     ses paramètres d'instance sont déplacés dans une subentry homonyme.
  2. Les entries v2 suivantes sont absorbées comme subentries du hub puis
     supprimées de l'index `core.config_entries`.
- **`unique_id` préservé sur chaque subentry** → les `entity_id`
  (`sensor.bureau_next_open`, `button.rdc_test_close`, etc.) restent
  identiques. Aucune automation utilisateur n'est cassée.

### Modifié

- `ShuttersScheduler.__init__(hass, hub_entry, subentry)` au lieu de
  `(hass, entry)`. Les paramètres d'instance se lisent depuis
  `subentry.data` ; les paramètres de notification depuis
  `hub_entry.data` (relus à chaque appel pour suivre les changements de
  l'options flow sans reload).
- Les entities (`sensor`, `switch`, `button`) sont rattachées à la
  bonne subentry via `async_add_entities(..., config_subentry_id=…)` —
  l'UI HA affiche désormais 1 device par instance, sous le device hub.
- `signal_state_update` est scopé par `subentry_id` (et plus par
  `entry_id`) — les sensors/switches d'une instance ne réagissent qu'à
  leurs propres events.
- Services `run_now`, `pause`, `resume` : itèrent désormais
  `hass.data[DOMAIN]` qui est indexé par `subentry_id`. Comportement
  visible inchangé (broadcast à toutes les instances).

### Tests

- Refactor complet de la suite : nouvelle fixture commune
  `setup_integration` qui produit un hub v3 avec une subentry « Bureau »,
  helpers `get_only_subentry_id()` et `build_hub_with_instance()` dans
  `conftest.py`.
- `tests/test_config_flow.py` réécrit : couvre le flow hub (création +
  abort singleton + options) et le flow subentry (création + erreurs +
  duplicate + reconfigure).
- **Nouveau** `tests/test_migration.py` (4 cas) : promotion d'une entry
  isolée, fold de 2 entries en 1 hub, no-op sur hub natif, préservation
  du `unique_id` pour la stabilité des entity_id.
- **Nouveau** `tests/test_notifications.py` (10 cas) : liste vide,
  open/close, multi-services, toggle away-only, localisation FR/EN,
  robustesse face à un notifier cassé, cibles malformées.
- Suite complète : **66 tests verts**.

### Note de migration utilisateur

- **Aucune action requise**. Au premier démarrage en v0.4.0, vos entries
  v0.3.x sont converties automatiquement en subentries d'un hub
  « Shutters Management » singleton. Les `entity_id`, les noms de
  devices, les automations, les cards Lovelace continuent de
  fonctionner sans modification.
- Pour configurer les notifications, ouvrez **Paramètres → Appareils
  et services → Shutters Management → Configurer** : multi-select des
  services `notify.*` + toggle d'absence.
- Pour ajouter un nouveau planning, allez sur la device card du hub
  et cliquez sur **« + »** (« Add a shutter schedule » / « Ajouter un
  planning de volets »).

## [0.3.5] — 2026-04-30

### Corrigé

- Bump de la version de l'intégration `0.3.4` → `0.3.5` dans `manifest.json`.
- **Vraie correction du bug d'`entity_id` traduit** introduit par HA quand `_attr_has_entity_name = True` + `_attr_translation_key` + `_attr_device_info[name]` sont combinés.
- La v0.3.4 utilisait `_attr_suggested_object_id`, **propriété fantôme** : Home Assistant ne lit jamais cet attribut comme source d'`entity_id`. Dans `homeassistant/helpers/entity.py`, seule la *property* `Entity.suggested_object_id` est consultée — et elle retourne le nom traduit. La valeur passée via `_attr_suggested_object_id` finissait dans `object_id_base` (priorité plus basse que le nom traduit), donc le bug subsistait pour 4 entités sur 5 (`next_open`, `next_close`, `test_open`, `test_close`).
- v0.3.5 utilise le **pattern documenté** par `entity_platform.py:823-845` : assignation directe de `self.entity_id = "<platform>.<prefix>_<translation_key>"` dans `__init__`. HA capte alors la valeur dans `internal_integration_suggested_object_id` (priorité maximale), bypassant entièrement la lookup de traduction.
- La helper `_build_suggested_object_id(entry, translation_key)` est remplacée par `_build_entity_id(platform, entry, translation_key)` dans `custom_components/shutters_management/entities.py` :
  - `f"{platform}.{entry.unique_id}_{translation_key}"` quand `unique_id` est défini ;
  - `f"{platform}.{slugify(entry.title)}_{translation_key}"` en fallback.
- Chaque classe d'entité (`ShuttersNextTriggerSensor`, `ShuttersSimulationSwitch`, `ShuttersRunNowButton`) pose désormais `self.entity_id = suggested` dans son `__init__` lorsque la helper renvoie une valeur non `None`.
- Vérifié empiriquement : les `entity_id` sont maintenant `sensor.<slug>_next_open`, `sensor.<slug>_next_close`, `button.<slug>_test_open`, `button.<slug>_test_close`, `switch.<slug>_simulation_active` quelle que soit la langue HA active. Les libellés affichés dans les cartes du dashboard restent localisés (ils dépendent du `translation_key`, pas de l'`entity_id`).

### Note de migration

- **Identique à v0.3.4** : les entités créées avant ce correctif conservent leur `entity_id` historique, le registry HA stocke l'`entity_id` à la création initiale et ne le recalcule pas. Pour basculer sur les nouveaux IDs anglais, deux options :
  1. Renommer manuellement chaque entité depuis **Paramètres → Appareils et services → Shutters Management → cliquer sur l'entité → modifier l'`entity_id`**.
  2. Supprimer puis recréer l'instance après redémarrage HA.
- Aucune migration de schéma. Le `unique_id`, le `translation_key`, le scheduler, les services et le config_flow sont strictement inchangés.

### Tests

- `tests/test_entities.py` : la classe `TestBuildSuggestedObjectId` est renommée `TestBuildEntityId` et chaque cas est mis à jour pour la nouvelle signature `_build_entity_id(platform, entry, translation_key)`. Ajout d'un test `test_platform_prefix_is_respected` qui couvre les 3 plateformes (`sensor`, `button`, `switch`).
- `tests/test_sensor.py` et `tests/test_multi_instance.py` : 3 assertions hardcodées (`next_opening` / `next_closing`) ajustées vers les nouveaux IDs anglais stables (`next_open` / `next_close`).
- Suite complète : **50 tests verts** (49 existants ajustés + 1 nouveau).

## [0.3.4] — 2026-04-30

### Corrigé

- Bump de la version de l'intégration `0.3.3` → `0.3.4` dans `manifest.json`.
- **Correction d'un bug latent côté Home Assistant** : sans `_attr_suggested_object_id`, HA dérive l'`object_id` d'une entité du **nom traduit dans la langue active au moment de la création**. Concrètement, une instance ajoutée alors que l'UI HA est en français produisait des `entity_id` français (par ex. `button.bureau_tester_l_ouverture`, `sensor.bureau_prochaine_fermeture`) plutôt que les identifiants anglais stables attendus (`button.bureau_test_open`, `sensor.bureau_next_close`), et ce **même si le `translation_key` est anglais**.
- 4 entités sur 5 étaient sensibles à la langue de création : `sensor next_open`, `sensor next_close`, `button test_open`, `button test_close`. Le `switch simulation_active` n'était pas impacté car son libellé fr/en est identique.
- Le correctif (transposé du fix `pool_control` v0.0.21) introduit une helper partagée `custom_components/shutters_management/entities.py::_build_suggested_object_id(entry, translation_key)` qui calcule un `object_id` stable :
  - `f"{entry.unique_id}_{translation_key}"` quand `entry.unique_id` est défini ;
  - `f"{slugify(entry.title)}_{translation_key}"` en fallback pour les entries héritées sans `unique_id`.
- Chaque classe d'entité (`ShuttersNextTriggerSensor`, `ShuttersSimulationSwitch`, `ShuttersRunNowButton`) pose `self._attr_suggested_object_id` dans son `__init__` après la fixation du `translation_key`.

### Note de migration

- **Les entités créées avant ce correctif conservent leur `entity_id` historique** tant que leur `unique_id` reste inchangé : HA stocke l'`entity_id` au moment de la création initiale dans le registry et ne le recalcule pas à partir du `suggested_object_id` lors d'un rechargement.
- Pour bénéficier des nouveaux IDs anglais, deux options :
  1. Renommer manuellement chaque entité depuis **Paramètres → Appareils et services → Shutters Management → cliquer sur l'entité → modifier l'`entity_id`**.
  2. Supprimer puis recréer l'instance (les `entity_id` régénérés à la nouvelle création seront stables et anglais quelle que soit la langue HA).
- Aucune migration de schéma n'est nécessaire ; le `unique_id`, le `translation_key` et la logique métier (scheduler, services, config_flow) sont strictement inchangés.

### Tests

- Ajout de `tests/test_entities.py` : 5 cas couvrent la helper (`entry=None`, `unique_id` défini, renommage du titre sans impact, fallback `slugify(entry.title)` quand `unique_id` est `None` ou `""`).
- Suite complète : **49 tests verts** (44 + 5 nouveaux).

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

[Non publié]: https://github.com/scadinot/shutters_management/compare/0.6.1...HEAD
[0.6.1]: https://github.com/scadinot/shutters_management/compare/0.6.0...0.6.1
[0.6.0]: https://github.com/scadinot/shutters_management/compare/0.5.8...0.6.0
[0.5.8]: https://github.com/scadinot/shutters_management/compare/0.5.7...0.5.8
[0.5.7]: https://github.com/scadinot/shutters_management/compare/0.5.6...0.5.7
[0.5.6]: https://github.com/scadinot/shutters_management/compare/0.5.5...0.5.6
[0.5.5]: https://github.com/scadinot/shutters_management/compare/0.5.4...0.5.5
[0.5.4]: https://github.com/scadinot/shutters_management/compare/0.5.3...0.5.4
[0.5.3]: https://github.com/scadinot/shutters_management/compare/0.5.2...0.5.3
[0.5.2]: https://github.com/scadinot/shutters_management/compare/0.5.1...0.5.2
[0.5.1]: https://github.com/scadinot/shutters_management/compare/0.5.0...0.5.1
[0.5.0]: https://github.com/scadinot/shutters_management/compare/0.4.11...0.5.0
[0.4.11]: https://github.com/scadinot/shutters_management/compare/0.4.10...0.4.11
[0.4.10]: https://github.com/scadinot/shutters_management/compare/0.4.9...0.4.10
[0.4.9]: https://github.com/scadinot/shutters_management/compare/0.4.8...0.4.9
[0.4.8]: https://github.com/scadinot/shutters_management/compare/0.4.7...0.4.8
[0.4.7]: https://github.com/scadinot/shutters_management/compare/0.4.6...0.4.7
[0.4.6]: https://github.com/scadinot/shutters_management/compare/0.4.5...0.4.6
[0.4.5]: https://github.com/scadinot/shutters_management/compare/0.4.4...0.4.5
[0.4.4]: https://github.com/scadinot/shutters_management/compare/0.4.3...0.4.4
[0.4.3]: https://github.com/scadinot/shutters_management/compare/0.4.2...0.4.3
[0.4.2]: https://github.com/scadinot/shutters_management/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/scadinot/shutters_management/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/scadinot/shutters_management/compare/0.3.5...0.4.0
[0.3.5]: https://github.com/scadinot/shutters_management/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/scadinot/shutters_management/compare/v0.3.3...v0.3.4
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
