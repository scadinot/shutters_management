# Shutters Management

[![Tests](https://github.com/scadinot/shutters_management/actions/workflows/tests.yaml/badge.svg)](https://github.com/scadinot/shutters_management/actions/workflows/tests.yaml)
[![HACS](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20HACS.yaml/badge.svg)](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20HACS.yaml)
[![Hassfest](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20Hassfest.yaml/badge.svg)](https://github.com/scadinot/shutters_management/actions/workflows/Validate%20Hassfest.yaml)

Intégration personnalisée Home Assistant (HACS) qui simule une présence en pilotant automatiquement vos volets roulants selon des horaires configurables, avec décalage aléatoire et prise en compte optionnelle de l'absence du foyer.

## Table des matières

- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation](#installation)
  - [Via HACS (recommandé)](#via-hacs-recommandé)
  - [Installation manuelle](#installation-manuelle)
- [Configuration](#configuration)
- [Comportement](#comportement)
- [Entités exposées](#entités-exposées)
- [Tableau de bord](#tableau-de-bord)
- [Services](#services)
- [Menu d'options](#menu-doptions)
- [Exemples d'utilisation](#exemples-dutilisation)
- [Dépannage](#dépannage)
- [FAQ](#faq)
- [Limitations connues](#limitations-connues)
- [Roadmap](#roadmap)
- [Contribuer](#contribuer)
- [Licence](#licence)

## Fonctionnalités

- Configuration entièrement par l'interface graphique (`config_flow`), modifiable à tout moment via les options.
- Sélection multiple d'entités `cover.*` pilotées simultanément.
- Heure d'ouverture et heure de fermeture indépendantes.
- Choix des jours de la semaine actifs (du lundi au dimanche).
- Décalage aléatoire optionnel (en minutes) pour éviter une régularité parfaite, plafonné automatiquement avant minuit pour ne pas déborder sur le jour suivant.
- Mode « uniquement en absence » : l'action ne se déclenche que si personne n'est à la maison.
- Choix d'une entité `person` ou `group` comme référence de présence, avec un repli automatique sur l'ensemble des `person.*` du système.
- Ré-évaluation des conditions au moment exact de l'exécution différée : si l'utilisateur revient pendant le délai aléatoire, l'action est annulée.
- Annulation propre des déclencheurs au déchargement ou au rechargement de l'intégration.
- Interface traduite en français et en anglais.

## Prérequis

- Home Assistant **2024.4.0** ou plus récent.
- Au moins une entité `cover.*` opérationnelle (volets roulants connectés à HA).
- Optionnel : une entité `person.*` ou `group.*` si vous souhaitez utiliser le mode « uniquement en absence » avec un suivi explicite.

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

L'intégration ne se configure pas en YAML. Tout passe par l'assistant graphique au moment de l'ajout, puis par l'écran **Options** ensuite.

| Champ | Type | Valeur par défaut | Description |
|---|---|---|---|
| `covers` | Liste d'entités `cover.*` | _(aucune)_ | Volets pilotés par l'intégration. Au moins un est requis. |
| `open_time` | Heure (`HH:MM:SS`) | `08:00:00` | Heure d'ouverture quotidienne (heure locale du système Home Assistant). |
| `close_time` | Heure (`HH:MM:SS`) | `21:00:00` | Heure de fermeture quotidienne (heure locale). |
| `days` | Liste de jours | Tous les jours | Jours où l'intégration est active. Valeurs : `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`. |
| `randomize` | Booléen | `true` | Active le décalage aléatoire à chaque déclenchement. |
| `random_max_minutes` | Entier (0 – 240) | `30` | Amplitude maximale du décalage aléatoire (en minutes). Ignoré si `randomize` est désactivé. |
| `only_when_away` | Booléen | `false` | Si activé, l'action ne se déclenche que si personne n'est détecté à la maison. |
| `presence_entity` | Entité `person` ou `group` | _(vide)_ | Référence explicite pour le mode absence. Optionnel ; sinon repli sur toutes les `person.*`. |

Les modifications via l'écran **Options** rechargent automatiquement l'intégration ; vous n'avez pas besoin de redémarrer Home Assistant.

## Comportement

### Horaires et fuseau horaire

Les heures d'ouverture et de fermeture sont interprétées dans le **fuseau horaire local de Home Assistant** (celui défini dans `Paramètres → Système → Général`). Le système gère seul les changements heure d'été / heure d'hiver.

### Décalage aléatoire

Lorsque `randomize` est actif, un délai aléatoire entre `0` et `random_max_minutes` minutes est appliqué à chaque déclenchement, recalculé à chaque fois. Pour éviter qu'une action ne déborde sur le lendemain (et change donc de jour actif), le délai est automatiquement plafonné au temps restant avant minuit. Programmer une action à 23 h 55 avec 30 min d'amplitude limitera donc le décalage à 5 min.

### Ré-évaluation différée

Si le décalage aléatoire repousse l'exécution dans le futur, les conditions (jour actif, mode absence, état de présence) sont **vérifiées à nouveau au moment exact de l'exécution**. Concrètement :

- Si vous rentrez pendant le délai et que `only_when_away` est activé, l'action n'est pas exécutée.
- Si l'intégration est rechargée pendant le délai, le déclenchement programmé est annulé proprement.

### Logique de présence

Quand `only_when_away` est activé, l'intégration applique l'ordre suivant :

1. Si une `presence_entity` est configurée : son état est consulté. L'absence est détectée pour les états `not_home` ou `away`.
2. Sinon, repli sur toutes les entités `person.*` du système : la condition est satisfaite si **toutes** sont absentes.
3. Si aucune entité `person.*` n'existe et qu'aucune n'est configurée : la simulation s'exécute par défaut (un avertissement est inscrit dans le journal de Home Assistant).

## Entités exposées

L'intégration crée cinq entités regroupées sous un device unique « Shutters Management » :

| Entité | Type | Description |
|---|---|---|
| `sensor.shutters_management_next_opening` | `timestamp` | Date et heure du prochain déclenchement d'ouverture (sans le décalage aléatoire). |
| `sensor.shutters_management_next_closing` | `timestamp` | Date et heure du prochain déclenchement de fermeture. |
| `switch.shutters_management_simulation_active` | `switch` | État actif/pause de la simulation. Togglable directement depuis le dashboard. |
| `button.shutters_management_test_open` | `button` | Déclenche immédiatement une ouverture des volets configurés. |
| `button.shutters_management_test_close` | `button` | Déclenche immédiatement une fermeture des volets configurés. |

Les noms exacts des entités peuvent varier selon votre langue ; les `unique_id` restent stables (`<entry_id>_next_open`, `<entry_id>_next_close`, `<entry_id>_simulation_active`, `<entry_id>_test_open`, `<entry_id>_test_close`).

Les capteurs `next_*` n'incluent pas le décalage aléatoire : ils annoncent l'heure programmée. Le décalage est appliqué au moment du déclenchement. Quand le switch est sur `off` (simulation en pause), les capteurs renvoient `unknown`.

### Migration depuis la v0.2.0

> **Breaking change v0.2.1** — le `binary_sensor.shutters_management_simulation_active` a été remplacé par un `switch.shutters_management_simulation_active` togglable. Les automations qui référencent l'ancienne entité doivent être mises à jour pour pointer vers le switch (les états restent `on` / `off`). Selon votre registre des entités existant, l'ancien `binary_sensor` peut rester présent comme entité obsolète ou indisponible après la mise à jour ; si c'est le cas, vous pouvez le supprimer manuellement du registre des entités.

## Tableau de bord

Les entités actionnables s'intègrent directement dans Lovelace. Exemple de carte combinant le switch et les deux boutons de test, avec les capteurs d'horodatage :

```yaml
type: entities
title: Volets
entities:
  - entity: switch.shutters_management_simulation_active
    name: Simulation
  - entity: sensor.shutters_management_next_opening
  - entity: sensor.shutters_management_next_closing
  - type: button
    name: Tester l'ouverture
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.shutters_management_test_open
  - type: button
    name: Tester la fermeture
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.shutters_management_test_close
```

Vous pouvez aussi ajouter directement les entités `button.*` dans une carte « Entités » : un appui suffit à déclencher l'action.

## Services

L'intégration enregistre trois services au niveau du domaine `shutters_management`.

### `shutters_management.run_now`

Déclenche immédiatement une ouverture ou une fermeture des volets configurés. Les conditions habituelles (jour actif, présence, décalage aléatoire) sont **ignorées** : c'est un mode test manuel.

| Champ | Obligatoire | Valeurs | Description |
|---|---|---|---|
| `action` | oui | `open`, `close` | Action à exécuter. |

Exemple YAML :

```yaml
service: shutters_management.run_now
data:
  action: open
```

### `shutters_management.pause`

Met la simulation en pause. Les déclenchements programmés sont ignorés tant que la simulation n'a pas repris. Le `switch.shutters_management_simulation_active` passe à `off`.

```yaml
service: shutters_management.pause
```

### `shutters_management.resume`

Reprend la simulation après une pause. Le switch repasse à `on`.

```yaml
service: shutters_management.resume
```

## Menu d'options

L'écran **Configurer** de l'intégration propose désormais un menu :

- **Modifier la configuration** : édite les volets, les heures, les jours, etc.
- **Tester : ouvrir maintenant** : déclenche une ouverture immédiate (équivalent au service `run_now` avec `action: open`).
- **Tester : fermer maintenant** : déclenche une fermeture immédiate.
- **Mettre la simulation en pause** ou **Reprendre la simulation** : selon l'état courant.

## Exemples d'utilisation

### Usage standard

Trois volets de salon (`cover.salon_droit`, `cover.salon_gauche`, `cover.salle_a_manger`), ouverture à 7 h 30 ± 20 min et fermeture à 22 h 00 ± 20 min, tous les jours. Mode absence désactivé : la simulation tourne en permanence pour que les voisins voient une activité régulière.

### Simulation pendant les vacances

Mêmes volets, ouverture 8 h 15 ± 30 min et fermeture 21 h 30 ± 30 min, tous les jours, **avec** `only_when_away` activé et `presence_entity` réglé sur un groupe `group.famille`. L'intégration ne pilote rien tant que le groupe n'est pas en `not_home`.

### Week-end uniquement

Réservé aux samedi et dimanche : ouverture 9 h 30 ± 60 min, fermeture 23 h 00 ± 30 min, jours = `sat`, `sun`. Utile pour rajouter une variabilité sur les jours où vous êtes parfois absent.

## Dépannage

**Les volets ne bougent pas du tout.**
Vérifiez dans **Outils de développement → Services** que `cover.open_cover` et `cover.close_cover` fonctionnent manuellement sur les entités sélectionnées. Si oui, contrôlez le journal de Home Assistant : tout déclenchement ou skip y est tracé en niveau `DEBUG`. Activez le debug dans `configuration.yaml` :

```yaml
logger:
  default: warning
  logs:
    custom_components.shutters_management: debug
```

**`only_when_away` semble ignoré.**
Vérifiez que l'entité de présence (ou les `person.*` détectées) basculent bien en `not_home` quand vous quittez la maison. Une `presence_entity` non configurée et aucune `person.*` connue déclenche un avertissement dans les logs et fait tourner la simulation par défaut.

**Le décalage aléatoire semble plus court que prévu.**
Si l'heure programmée est proche de minuit (ex. 23 h 50), l'amplitude est plafonnée pour ne pas déborder sur le lendemain. C'est intentionnel.

**Une modification dans Options n'a pas d'effet.**
Le rechargement est automatique. Si rien ne change, supprimez l'intégration et reconfigurez-la — un avertissement éventuel apparaîtra dans le journal.

## FAQ

**Puis-je avoir plusieurs profils horaires (semaine / week-end / vacances) ?**
Pas dans la version actuelle : une seule instance est gérée. C'est prévu dans la [roadmap](ROADMAP.md).

**Puis-je piloter par des heures relatives au coucher du soleil ?**
Pas encore. Voir la [roadmap](ROADMAP.md) (v0.3).

**L'intégration expose-t-elle des entités ou services pour automatisation ?**
Oui : voir les sections [Entités exposées](#entités-exposées) et [Services](#services).

**Que se passe-t-il si Home Assistant redémarre pendant un délai aléatoire ?**
Le délai en attente est perdu (comportement standard d'`async_call_later`). Le prochain déclenchement programmé reprend normalement.

## Limitations connues

- Une seule instance de l'intégration peut être configurée par installation Home Assistant.
- Pas de support des déclencheurs liés au soleil (`sunset` / `sunrise`).

Ces limitations sont suivies dans la [roadmap](ROADMAP.md).

## Roadmap

Voir le fichier [ROADMAP.md](ROADMAP.md) pour la liste des évolutions prévues et l'état d'avancement.

## Contribuer

Les contributions sont les bienvenues : ouvrez d'abord une issue pour décrire le besoin avant de proposer une pull request, surtout pour les évolutions importantes.

Structure du dépôt :

```
shutters_management/
├── custom_components/
│   └── shutters_management/
│       ├── __init__.py        # logique de planification
│       ├── button.py          # boutons "tester ouverture/fermeture"
│       ├── config_flow.py     # assistant UI + options
│       ├── const.py           # constantes
│       ├── manifest.json
│       ├── sensor.py          # sensors prochaine ouverture/fermeture
│       ├── strings.json
│       ├── switch.py          # switch actif/pause
│       └── translations/
│           ├── en.json
│           └── fr.json
├── tests/                     # suite pytest
├── .github/workflows/         # CI GitHub Actions
├── pyproject.toml
├── requirements_test.txt
├── hacs.json
├── README.md
├── ROADMAP.md
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

La CI GitHub Actions (`.github/workflows/tests.yml`) exécute la même commande sur Python 3.12 et 3.13 à chaque push sur `main` et chaque pull request.

## Licence

Distribué sous licence MIT. Voir [LICENSE](LICENSE) pour le texte complet.
