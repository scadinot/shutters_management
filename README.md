# Shutters Management

[![Tests](https://github.com/scadinot/shutters_management/actions/workflows/tests.yaml/badge.svg)](https://github.com/scadinot/shutters_management/actions/workflows/tests.yaml)
[![HACS](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20HACS.yaml/badge.svg)](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20HACS.yaml)
[![Hassfest](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20Hassfest.yaml/badge.svg)](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20Hassfest.yaml)

Intégration personnalisée Home Assistant (HACS) qui pilote automatiquement vos volets roulants suivant trois logiques complémentaires : **planification** déterministe (heure fixe ou décalée par rapport au lever/coucher du soleil), **simulation de présence** avec décalage aléatoire et prise en compte de l'absence du foyer, et **protection solaire** adaptative (lux + UV + températures intérieure/extérieure avec hystérésis et debounce). Notifications push et annonces vocales TTS partagées au niveau du hub, modes paramétrables par sous-entrée.

## Table des matières

- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation](#installation)
  - [Via HACS (recommandé)](#via-hacs-recommandé)
  - [Installation manuelle](#installation-manuelle)
- [Configuration](#configuration)
  - [Hub — réglages partagés](#hub--réglages-partagés)
  - [Sous-entrée Planification (`instance`)](#sous-entrée-planification-instance)
  - [Sous-entrée Simulation de présence (`presence_simulation`)](#sous-entrée-simulation-de-présence-presence_simulation)
  - [Sous-entrée Protection solaire (`sun_protection`)](#sous-entrée-protection-solaire-sun_protection)
- [Comportement](#comportement)
  - [Logique de présence](#logique-de-présence)
  - [Modes par canal](#modes-par-canal)
  - [Protection solaire](#protection-solaire)
- [Entités exposées](#entités-exposées)
- [Tableau de bord](#tableau-de-bord)
- [Services](#services)
- [Modifier la configuration](#modifier-la-configuration)
- [Exemples d'utilisation](#exemples-dutilisation)
- [Dépannage](#dépannage)
- [FAQ](#faq)
- [Limitations connues](#limitations-connues)
- [Roadmap](#roadmap)
- [Changelog](#changelog)
- [Contribuer](#contribuer)
- [Licence](#licence)

## Fonctionnalités

### Architecture

- Configuration entièrement par l'interface graphique (`config_flow`),
  modifiable à tout moment via **Configurer** (hub) et **Reconfigurer**
  (chaque sous-entrée).
- Pattern **hub + sous-entrées** : un hub unique partage les canaux
  (notifications, TTS, présence, capteurs Sun Protection) entre
  plusieurs sous-entrées indépendantes. Trois types de sous-entrée :
  - **Planification** — déclenchements déterministes (heure fixe ou
    décalée par rapport au lever/coucher du soleil).
  - **Simulation de présence** — comme la planification, plus un
    décalage aléatoire et un mode « uniquement en absence ».
  - **Protection solaire** — fermeture automatique d'un groupe de
    volets selon une combinaison lux + UV + températures
    intérieure/extérieure (logique adaptative avec hystérésis,
    debounce et override manuel).

### Pilotage des volets

- Sélection multiple d'entités `cover.*` par sous-entrée.
- Heure d'ouverture et heure de fermeture indépendantes ; trois modes
  par événement : `fixed`, `sunrise` ou `sunset` avec offset signé.
- Choix des jours actifs (du lundi au dimanche).
- Décalage aléatoire optionnel (en minutes), automatiquement plafonné
  pour ne pas déborder sur le jour suivant — réservé à la simulation
  de présence.
- Mode « actionner les volets séquentiellement dans un ordre
  aléatoire » au niveau du hub.
- Ré-évaluation des conditions (jour, présence) au moment exact de
  l'exécution différée : si l'utilisateur revient pendant le délai
  aléatoire, l'action est annulée.

### Notifications et annonces

- Multi-select des services `notify.*` au hub, mode par sous-entrée :
  `disabled` / `always` / `away_only`.
- Annonces vocales TTS sur des `media_player.*` au hub, mode par
  sous-entrée : `disabled` / `always` / `home_only`.
- Sélecteur **multi-entités** de présence au hub (depuis v0.7.1) :
  une ou plusieurs entités `person.*` / `group.*`. Repli automatique
  sur toutes les `person.*` du système. Le foyer est considéré
  *absent* quand toutes les entités configurées rapportent un état
  d'absence.
- Une notification cassée ne bloque jamais l'action sur les volets.

### Robustesse

- Annulation propre des déclencheurs au déchargement ou au
  rechargement de l'intégration.
- Migration automatique des données entre versions
  (`ENTRY_VERSION = 8` actuellement).
- Interface traduite en français et en anglais.

## Prérequis

- Home Assistant **2026.3.0** ou plus récent (cette version introduit
  le chargement des assets de marque embarqués dans
  `custom_components/<domain>/brand/`).
- Au moins une entité `cover.*` opérationnelle (volets roulants
  connectés à HA).
- Optionnel : une ou plusieurs entités `person.*` / `group.*` si vous
  utilisez les modes basés sur la présence (`away_only`, `home_only`)
  ou le mode « uniquement en absence » de la simulation de présence.
- Optionnel : pour la **protection solaire**, un capteur de luminosité
  extérieur (lux) ou un capteur d'indice UV ; un capteur de
  température extérieure et un capteur de température intérieure
  améliorent la pertinence des seuils.

## Installation

### Via HACS (recommandé)

1. Ouvrez **HACS** dans Home Assistant.
2. Allez dans **Intégrations** puis ouvrez le menu **⋮** en haut à droite et choisissez **Custom repositories**.
3. Ajoutez l'URL du dépôt GitHub : `https://github.com/scadinot/shutters_management`.
4. Sélectionnez le type **Integration**.
5. Validez. L'intégration apparaît alors dans la liste — installez-la.
6. Redémarrez Home Assistant.
7. Allez dans **Paramètres → Appareils et services → Ajouter une intégration**, recherchez **Shutters Management** et suivez l'assistant de configuration.

### Installation manuelle

1. Téléchargez la dernière version du dépôt.
2. Copiez le dossier `custom_components/shutters_management/` dans le dossier `config/custom_components/` de votre installation Home Assistant.
3. Redémarrez Home Assistant.
4. Ajoutez l'intégration depuis **Paramètres → Appareils et services → Ajouter une intégration**.

## Configuration

L'intégration ne se configure pas en YAML. Tout passe par l'assistant
graphique au moment de l'ajout, puis :

- **Configurer** sur l'intégration → réglages du **hub**.
- **⋮ → Reconfigurer** sur chaque sous-entrée → réglages d'une
  planification, d'une simulation de présence ou d'une protection
  solaire.

Tous les panneaux sont repliés par défaut (depuis v0.6.3). Les
modifications appliquées rechargent automatiquement l'intégration ;
aucun redémarrage de Home Assistant n'est nécessaire.

### Hub — réglages partagés

Le hub est créé automatiquement à la première installation. Il regroupe
les canaux de communication, l'entité de présence partagée et les
capteurs externes utilisés par la protection solaire.

| Champ | Type | Valeur par défaut | Description |
|---|---|---|---|
| `notify_services` | Liste `notify.*` | _(vide)_ | Services de notification push appelés après chaque action. |
| `tts_engine` | Entité `tts.*` | _(vide)_ | Moteur TTS utilisé pour les annonces vocales. |
| `tts_targets` | Liste `media_player.*` | _(vide)_ | Enceintes destinataires des annonces vocales. |
| `presence_entity` | Liste `person.*` / `group.*` | _(vide)_ | Entités utilisées par les modes `away_only` / `home_only` et par `only_when_away`. Repli automatique sur toutes les `person.*` du système quand la liste est vide. Multi-sélection depuis v0.7.1. |
| `lux_entity` | Entité `sensor` | _(vide)_ | Capteur de luminosité extérieure (lux). Capteur primaire de la protection solaire. |
| `uv_entity` | Entité `sensor` | _(vide)_ | Capteur d'indice UV. Alternative ou complément additif au lux. |
| `temp_outdoor_entity` | Entité `sensor` | _(vide)_ | Température extérieure (°C). Active la table de seuils adaptatifs. |
| `sequential_covers` | Booléen | `false` | Actionner les volets un par un, dans un ordre aléatoire, plutôt qu'en parallèle. |

### Sous-entrée Planification (`instance`)

Déclenchements déterministes, sans aléa.

| Champ | Type | Valeur par défaut | Description |
|---|---|---|---|
| `name` | Texte | _(requis)_ | Identifiant logique de la sous-entrée (Bureau, RDC, Terrasse, …). Sert de préfixe aux entités exposées. |
| `covers` | Liste `cover.*` | _(aucune)_ | Volets pilotés. Au moins un est requis. |
| `open_mode` | `fixed` / `sunrise` / `sunset` | `fixed` | Type de déclencheur d'ouverture. |
| `open_time` | Heure (`HH:MM:SS`) | `08:00:00` | Heure d'ouverture quotidienne, **uniquement si `open_mode = fixed`**. |
| `open_offset` | Entier signé (-360 – +360 min) | `0` | Décalage par rapport au lever/coucher, **uniquement si `open_mode != fixed`**. |
| `close_mode` | `fixed` / `sunrise` / `sunset` | `fixed` | Type de déclencheur de fermeture. |
| `close_time` | Heure (`HH:MM:SS`) | `21:00:00` | Heure de fermeture, **uniquement si `close_mode = fixed`**. |
| `close_offset` | Entier signé (-360 – +360 min) | `0` | Décalage par rapport au lever/coucher, **uniquement si `close_mode != fixed`**. |
| `days` | Liste de jours | Tous | Jours actifs : `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`. |
| `notify_mode` | `disabled` / `always` / `away_only` | `always` | Pousser une notification après chaque action. Voir [Logique de présence](#logique-de-présence). |
| `tts_mode` | `disabled` / `always` / `home_only` | `disabled` | Annoncer chaque action sur les enceintes configurées au hub. |

### Sous-entrée Simulation de présence (`presence_simulation`)

Tous les champs de la planification, plus :

| Champ | Type | Valeur par défaut | Description |
|---|---|---|---|
| `randomize` | Booléen | `true` | Active le décalage aléatoire à chaque déclenchement. |
| `random_max_minutes` | Entier (0 – 240) | `30` | Amplitude maximale du décalage aléatoire (en minutes). Ignoré si `randomize` est désactivé. |
| `only_when_away` | Booléen | `false` | Si activé, l'action ne se déclenche que si le foyer est détecté absent (cf. [Logique de présence](#logique-de-présence)). |

### Sous-entrée Protection solaire (`sun_protection`)

Active la fermeture automatique d'un groupe de volets selon
l'orientation de la façade et les capteurs configurés au hub. La
logique adaptative (lux × T_ext × T_pièce) est détaillée dans le
[CHANGELOG v0.6.0](CHANGELOG.md#060--2026-05-04).

| Champ | Type | Valeur par défaut | Description |
|---|---|---|---|
| `name` | Texte | _(requis)_ | Identifiant logique du groupe (Salon Sud, Toiture Ouest, …). |
| `covers` | Liste `cover.*` | _(aucune)_ | Volets de la façade. |
| `orientation` | `n` / `ne` / `e` / `se` / `s` / `sw` / `w` / `nw` | `s` | Orientation cardinale de la façade. |
| `arc` | Entier (0 – 180 °) | `60` | Demi-largeur de l'arc azimutal autour de l'orientation. |
| `min_elevation` | Entier (0 – 90 °) | `15` | Élévation minimale du soleil pour considérer la façade comme exposée. |
| `min_uv` | Entier (0 – 11) | `3` | Seuil UV (utilisé seulement si un `uv_entity` est configuré au hub). |
| `target_position` | Entier (0 – 100 %) | `50` | Position cible des volets quand la protection se déclenche. |
| `temp_indoor_entity` | Entité `sensor` | _(vide)_ | Capteur de température de la pièce. Sans ce capteur, le critère de température pièce est sauté. |
| `notify_mode` | `disabled` / `always` / `away_only` | `always` | Notification push lors d'une fermeture / réouverture solaire. |
| `tts_mode` | `disabled` / `always` / `home_only` | `disabled` | Annonce vocale lors d'une fermeture / réouverture solaire. |

## Comportement

### Horaires et fuseau horaire

Les heures d'ouverture et de fermeture sont interprétées dans le
**fuseau horaire local de Home Assistant** (celui défini dans
`Paramètres → Système → Général`). Le système gère seul les
changements heure d'été / heure d'hiver.

### Décalage aléatoire (simulation de présence uniquement)

Lorsque `randomize` est actif, un délai aléatoire entre `0` et
`random_max_minutes` minutes est appliqué à chaque déclenchement,
recalculé à chaque fois. Pour éviter qu'une action ne déborde sur le
lendemain (et change donc de jour actif), le délai est automatiquement
plafonné au temps restant avant minuit. Programmer une action à
23 h 55 avec 30 min d'amplitude limitera donc le décalage à 5 min.

### Ré-évaluation différée

Si le décalage aléatoire repousse l'exécution dans le futur, les
conditions (jour actif, mode absence, état de présence) sont
**vérifiées à nouveau au moment exact de l'exécution**. Concrètement :

- Si vous rentrez pendant le délai et que `only_when_away` est
  activé, l'action n'est pas exécutée.
- Si l'intégration est rechargée pendant le délai, le déclenchement
  programmé est annulé proprement.

### Logique de présence

Le foyer est considéré *absent* (états `not_home` ou `away`) selon
l'algorithme suivant :

1. Si une ou plusieurs entités sont configurées dans `presence_entity`
   au **hub** : toutes doivent rapporter un état d'absence pour que
   le foyer soit considéré absent.
2. Une entité dont l'état est `unavailable` ou `unknown` est ignorée
   (un avertissement est inscrit dans le journal).
3. Si toutes les entités configurées sont indisponibles, ou si la
   liste est vide, repli sur toutes les `person.*` du système : la
   condition est satisfaite si **toutes** sont absentes.
4. Si aucune `person.*` n'existe : la simulation s'exécute par
   défaut (« assume away »), un avertissement est inscrit dans le
   journal.

### Modes par canal

Les modes `notify_mode` (notifications push) et `tts_mode` (annonces
vocales) sont indépendants et évalués séparément à chaque action.

| Mode | `notify_mode` | `tts_mode` | Effet |
|---|---|---|---|
| `disabled` | ✓ | ✓ | Le canal ne se déclenche jamais. |
| `always` | ✓ | ✓ | Le canal se déclenche à chaque action. |
| `away_only` | ✓ | — | Le canal ne se déclenche que si le foyer est *absent*. |
| `home_only` | — | ✓ | Le canal ne se déclenche que si au moins une entité de présence est *à la maison*. |

Une notification ou annonce qui échoue (service indisponible,
moteur TTS planté…) ne bloque jamais l'action sur les volets : la
commande `cover.open_cover` / `cover.close_cover` est appelée en
premier et indépendamment.

### Protection solaire

L'algorithme adaptatif (lux × UV × T_ext × T_pièce) avec hystérésis,
debounce et override manuel est détaillé dans le
[CHANGELOG v0.6.0](CHANGELOG.md#060--2026-05-04). Les 15 entités
diagnostic exposées par groupe (statut, marges, valeurs de capteurs)
sont décrites dans le [CHANGELOG v0.6.1](CHANGELOG.md#061--2026-05-04).

## Entités exposées

Chaque sous-entrée crée son propre device « Shutters Management », et
les entités sont préfixées par le slug du `name` de la sous-entrée
(exemples ci-dessous avec « Bureau »). Les `unique_id` restent
indépendants du nom (`<subentry_id>_<key>`).

### Planification et Simulation de présence

| Entité | Type | Description |
|---|---|---|
| `sensor.bureau_next_open` | `timestamp` | Date et heure du prochain déclenchement d'ouverture (sans le décalage aléatoire). |
| `sensor.bureau_next_close` | `timestamp` | Date et heure du prochain déclenchement de fermeture. |
| `switch.bureau_simulation_active` | `switch` | État actif/pause de la sous-entrée. |
| `button.bureau_test_open` | `button` | Déclenche immédiatement une ouverture des volets configurés. |
| `button.bureau_test_close` | `button` | Déclenche immédiatement une fermeture des volets configurés. |

Les capteurs `next_*` n'incluent pas le décalage aléatoire : ils
annoncent l'heure programmée. Le décalage est appliqué au moment du
déclenchement. Quand le switch est sur `off` (sous-entrée en pause),
les capteurs renvoient `unknown`.

### Protection solaire

Pour chaque sous-entrée de protection solaire, on crée :

- `binary_sensor.<groupe>_sun_protection_active` — `on` quand
  l'algorithme demande une fermeture, avec attributs détaillés
  (`status`, `lux`, `uv_index`, `temp_outdoor`, `temp_indoor`,
  `override_until`).
- `binary_sensor.<groupe>_sun_facing` — `on` quand le soleil est
  géométriquement face à la façade (azimut + élévation),
  indépendamment des autres conditions.
- `switch.<groupe>_sun_protection` — interrupteur d'activation du
  groupe.
- **14 capteurs Diagnostic** (statut, marges, valeurs de capteurs,
  prochain reset d'override) masqués par défaut sur les dashboards.
  Liste exhaustive et description dans le
  [CHANGELOG v0.6.1](CHANGELOG.md#061--2026-05-04).

### Notes de migration

> **v0.2.1** : le `binary_sensor.*_simulation_active` historique a
> été remplacé par un `switch.*_simulation_active` basculable.
>
> **v0.2.3** : les `entity_id` sont désormais figés sur leur slug
> anglais pour les nouvelles installations. Les installations
> antérieures conservent leurs identifiants existants dans le
> registry pour ne pas casser les automations.
>
> **v0.3.0** : passage au pattern multi-instance ; le préfixe
> `<nom>` de chaque entité correspond au champ `name` saisi lors de
> la création de la sous-entrée.
>
> **v0.4.0 → v0.7.1** : passage à l'architecture **hub +
> sous-entrées**, avec une chaîne de migration automatique
> (`async_migrate_entry`) qui couvre l'intégralité des montées de
> version (`ENTRY_VERSION` actuel : 8). Les `entity_id` et
> `unique_id` sont préservés à chaque palier.

## Tableau de bord

Les entités actionnables s'intègrent directement dans Lovelace.
Exemple de carte pour une sous-entrée « Bureau », combinant le switch,
les deux boutons de test et les capteurs d'horodatage :

```yaml
type: entities
title: Volets — Bureau
entities:
  - entity: switch.bureau_simulation_active
    name: Simulation
  - entity: sensor.bureau_next_open
  - entity: sensor.bureau_next_close
  - type: button
    name: Tester l'ouverture
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.bureau_test_open
  - type: button
    name: Tester la fermeture
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.bureau_test_close
```

Vous pouvez aussi ajouter directement les entités `button.*` dans une
carte « Entités » : un appui suffit à déclencher l'action.

## Services

L'intégration enregistre trois services au niveau du domaine
`shutters_management`. Tous **diffusent** leur action à toutes les
sous-entrées concernées (broadcast). Le ciblage par sous-entrée est
listé dans la [roadmap](ROADMAP.md). En attendant, pour cibler une
sous-entrée précise depuis une automation, utilisez son entité
`switch.<nom>_simulation_active` ou ses `button.<nom>_test_*`.

### `shutters_management.run_now`

Déclenche immédiatement une ouverture ou une fermeture sur toutes les
planifications et simulations de présence. Les conditions habituelles
(jour actif, présence, décalage aléatoire) sont **ignorées** : c'est
un mode test manuel.

| Champ | Obligatoire | Valeurs | Description |
|---|---|---|---|
| `action` | oui | `open`, `close` | Action à exécuter. |

```yaml
service: shutters_management.run_now
data:
  action: open
```

### `shutters_management.pause`

Met en pause toutes les sous-entrées de planification et simulation
de présence. Les déclenchements programmés sont ignorés tant que la
sous-entrée n'a pas repris. Chaque `switch.<nom>_simulation_active`
passe à `off`.

```yaml
service: shutters_management.pause
```

### `shutters_management.resume`

Reprend toutes les sous-entrées en pause. Chaque switch repasse à
`on`.

```yaml
service: shutters_management.resume
```

## Modifier la configuration

- **Hub** — **Paramètres → Appareils et services → Shutters
  Management → Configurer**. Modifie les canaux partagés (notify,
  TTS, présence) et les capteurs Sun Protection.
- **Sous-entrée** — depuis la même page, ouvrir le menu **⋮** sur la
  sous-entrée concernée et choisir **Reconfigurer**. Modifie ses
  volets, ses horaires, ses modes de notification/TTS et — pour les
  simulations de présence — ses paramètres aléatoires.
- **Ajouter une sous-entrée** — depuis la même page, bouton
  **Ajouter une sous-entrée**, puis choisir le type (Planification,
  Simulation de présence, Protection solaire).

Toute modification recharge automatiquement l'intégration : aucun
redémarrage de Home Assistant n'est nécessaire.

Les actions ponctuelles (tester l'ouverture/la fermeture, mettre en
pause/reprendre) ne passent pas par cet écran ; elles sont disponibles
depuis le dashboard via les entités `button.<nom>_test_*` et
`switch.<nom>_simulation_active`, ou via les
[services](#services) `shutters_management.run_now` / `pause` /
`resume`.

## Exemples d'utilisation

### Usage standard — planification + simulation

Une **Planification** « Bureau » : deux volets
(`cover.bureau_nord`, `cover.bureau_sud`), ouverture à 7 h 30 et
fermeture à 22 h 00, du lundi au vendredi.

En parallèle, une **Simulation de présence** « Salon » : trois volets
(`cover.salon_droit`, `cover.salon_gauche`,
`cover.salle_a_manger`), ouverture 8 h 15 ± 30 min et fermeture
21 h 30 ± 30 min, tous les jours, avec `only_when_away = true` et
`notify_mode = away_only`. Pendant les vacances, vous recevez une
notification push à chaque mouvement, mais aucune annonce vocale dans
la maison vide.

### Protection solaire d'une baie sud

Sous-entrée **Protection solaire** « Salon Sud » : volets
`cover.salon_baie_sud`, `orientation = s`, `arc = 60°`,
`min_elevation = 15°`, `target_position = 30 %`,
`temp_indoor_entity = sensor.salon_temperature`. Au hub : capteurs
`lux_entity = sensor.lux_jardin` et
`temp_outdoor_entity = sensor.meteo_temp`. En canicule, les volets
descendent à 30 % d'ouverture dès 35 000 lux mesurés ; ils ne
remontent qu'après 20 minutes sous 25 000 lux.

### Multi-foyer avec deux entités de présence

Au hub : `presence_entity = [person.alice, person.bob]`. La maison
n'est considérée *absente* que si Alice **et** Bob sont en
`not_home`. Toutes les sous-entrées avec un mode `away_only` (notif
ou TTS) ou `only_when_away = true` (simulation) appliquent
automatiquement cette logique.

## Dépannage

**Les volets ne bougent pas du tout.**
Vérifiez dans **Outils de développement → Services** que
`cover.open_cover` et `cover.close_cover` fonctionnent manuellement
sur les entités sélectionnées. Si oui, contrôlez le journal de Home
Assistant : tout déclenchement ou skip y est tracé en niveau `DEBUG`.
Activez le debug dans `configuration.yaml` :

```yaml
logger:
  default: warning
  logs:
    custom_components.shutters_management: debug
```

**`only_when_away` ou `notify_mode = away_only` semble ignoré.**
Vérifiez la liste `presence_entity` du hub : toutes les entités
listées doivent rapporter `not_home` (ou `away`) pour que le foyer
soit considéré absent. Une entité `unavailable` / `unknown` est
ignorée — si toutes le sont, le repli sur les `person.*` du système
prend le relais.

**`tts_mode = home_only` ne parle jamais.**
Vérifiez que le hub a bien un `tts_engine` configuré et au moins un
`media_player` dans `tts_targets`. Vérifiez ensuite qu'au moins une
entité de présence est dans un état autre que `not_home` / `away` /
`unavailable` / `unknown`.

**Le décalage aléatoire semble plus court que prévu.**
Si l'heure programmée est proche de minuit (ex. 23 h 50), l'amplitude
est plafonnée pour ne pas déborder sur le lendemain. C'est
intentionnel.

**Une modification dans Configurer / Reconfigurer n'a pas d'effet.**
Le rechargement est automatique. Si rien ne change, supprimez la
sous-entrée et recréez-la — un avertissement éventuel apparaîtra
dans le journal.

**La protection solaire ne se déclenche pas.**
Consultez le `sensor.<groupe>_sun_protection_status` : il indique en
clair la condition non satisfaite (élévation trop basse, hors arc,
lux trop bas, température extérieure trop basse, override actif…).
Voir le [CHANGELOG v0.6.1](CHANGELOG.md#061--2026-05-04) pour la
liste des statuts.

## FAQ

**Puis-je avoir plusieurs profils horaires (semaine / week-end /
vacances) ?**
Pas directement, mais vous pouvez créer **plusieurs sous-entrées**
(par exemple une par profil horaire) et activer/désactiver celles
dont vous n'avez pas besoin via leur `switch.<nom>_simulation_active`.
Le support natif des profils horaires est prévu dans la
[roadmap](ROADMAP.md).

**Puis-je désigner plusieurs personnes comme référence de présence ?**
Oui depuis la v0.7.1. Le sélecteur `presence_entity` au hub accepte
plusieurs entités `person.*` et/ou `group.*`. Le foyer est considéré
*absent* uniquement quand toutes rapportent `not_home`. Avant
v0.7.1, il fallait passer par un `group.*` intermédiaire.

**Puis-je piloter par des heures relatives au coucher du soleil ?**
Oui. À la création d'une planification (ou simulation de présence),
choisissez le mode `sunrise` ou `sunset` comme déclencheur
d'ouverture ou de fermeture, puis renseignez un décalage signé en
minutes (`+30` = 30 min après l'événement, `-15` = 15 min avant).
Le décalage aléatoire reste appliqué en plus, pour la simulation de
présence.

**Différence entre `notify_mode = away_only` et `tts_mode =
home_only` ?**
`away_only` (notifications) ne fait sonner votre téléphone que quand
vous êtes parti — utile pour être averti d'une activité en votre
absence. `home_only` (annonces vocales) ne parle dans la maison que
quand quelqu'un est susceptible de l'entendre — éviter de parler
dans le vide. Les deux modes sont indépendants par sous-entrée.

**Une notification cassée bloque-t-elle l'action sur les volets ?**
Non. La commande `cover.open_cover` / `cover.close_cover` est
appelée en premier et indépendamment ; les notifications et annonces
vocales sont envoyées *après* avec `blocking=False`.

**L'intégration expose-t-elle des entités ou services pour
automatisation ?**
Oui : voir [Entités exposées](#entités-exposées) et
[Services](#services).

**Que se passe-t-il si Home Assistant redémarre pendant un délai
aléatoire ?**
Le délai en attente est perdu (comportement standard de
`async_call_later`). Le prochain déclenchement programmé reprend
normalement.

## Limitations connues

- Les services `shutters_management.run_now` / `pause` / `resume`
  agissent sur **toutes** les sous-entrées de planification et
  simulation de présence simultanément (broadcast). Le ciblage par
  `target` est prévu dans une release future. En attendant, pour
  cibler une sous-entrée spécifique, utilisez son
  `button.<nom>_test_*` ou son `switch.<nom>_simulation_active`.
- Les `notify_services` et `tts_targets` sont configurés au niveau du
  hub : tous les canaux configurés reçoivent les notifications de
  toutes les sous-entrées. Le ciblage par sous-entrée des canaux est
  identifié dans la [roadmap](ROADMAP.md).
- Les services `notify` et les annonces TTS ne se déclenchent **pas**
  sur `pause` ni `resume` (uniquement sur `open` / `close`).

Ces limitations sont suivies dans la [roadmap](ROADMAP.md).

## Roadmap

Voir le fichier [ROADMAP.md](ROADMAP.md) pour la liste des évolutions prévues et l'état d'avancement.

## Changelog

L'historique détaillé des versions est tenu dans [CHANGELOG.md](CHANGELOG.md), au format [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

## Contribuer

Les contributions sont les bienvenues : ouvrez d'abord une issue pour décrire le besoin avant de proposer une pull request, surtout pour les évolutions importantes.

Structure du dépôt :

```
shutters_management/
├── custom_components/
│   └── shutters_management/
│       ├── __init__.py        # scheduler + sun-protection manager
│       │                      #   + dispatcher notifications/TTS
│       │                      #   + chaîne de migration v2 → v8
│       ├── binary_sensor.py   # sun_protection_active + sun_facing
│       ├── brand/             # assets de marque (HA ≥ 2026.3)
│       │   ├── icon.png       # 256×256
│       │   ├── icon@2x.png    # 512×512
│       │   ├── logo.png       # 768×256
│       │   └── logo@2x.png    # 1536×512
│       ├── button.py          # boutons « tester ouverture/fermeture »
│       ├── config_flow.py     # hub flow + 3 subentry flows
│       ├── const.py           # constantes (modes, défauts, schéma)
│       ├── icons.json
│       ├── manifest.json
│       ├── sensor.py          # next_open / next_close +
│       │                      #   14 sensors diagnostic Sun Protection
│       ├── strings.json
│       ├── switch.py          # simulation_active + sun_protection
│       └── translations/
│           ├── en.json
│           └── fr.json
├── tests/                     # suite pytest
│   ├── conftest.py
│   ├── test_config_flow.py
│   ├── test_migration.py
│   ├── test_notifications.py
│   ├── test_scheduler.py
│   ├── test_sun_protection.py
│   ├── test_sun_protection_entities.py
│   ├── test_sun_trigger.py
│   ├── test_button.py
│   └── test_tts_announcements.py
├── .github/
│   ├── instructions/instructions.md
│   └── workflows/             # CI GitHub Actions
├── pyproject.toml
├── requirements_test.txt
├── hacs.json
├── README.md
├── ROADMAP.md
├── CHANGELOG.md
└── LICENSE
```

### Tester localement avec Home Assistant

Copiez le dossier `custom_components/shutters_management/` dans le `config/custom_components/` d'une instance Home Assistant de développement et redémarrez-la.

### Lancer la suite de tests

Depuis la racine du dépôt :

```bash
pip install -r requirements_test.txt
pytest
```

Pour la couverture détaillée :

```bash
pytest --cov=custom_components.shutters_management --cov-report=term-missing
```

La CI GitHub Actions (`.github/workflows/tests.yaml`) exécute la même commande sur Python 3.12 et 3.13 à chaque push sur `main` et chaque pull request. Deux workflows additionnels (`Validate HACS.yaml` et `Validate Hassfest.yaml`) valident la conformité de l'intégration aux standards HACS et Hassfest sur les mêmes déclencheurs, plus une exécution quotidienne planifiée.

## Licence

Distribué sous licence MIT. Voir [LICENSE](LICENSE) pour le texte complet.
