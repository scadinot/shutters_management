# Feuille de route — Shutters Management

Ce document recense les évolutions envisagées pour l'intégration, classées
par horizon (court / moyen / long terme) et par criticité. Chaque entrée
précise la **motivation** (pourquoi c'est utile) et, lorsque pertinent,
une **piste technique** (comment s'y prendre).

La liste est volontairement ouverte : ce ne sont pas toutes des promesses,
mais un réservoir d'idées à prioriser selon les besoins réels des
utilisateurs.

---

## Vue d'ensemble

| Horizon | Objectif principal | Effort estimé |
|---|---|---|
| [Statut actuel](#statut-actuel) | Version courante v0.2.4 — voir CHANGELOG pour l'historique | livré |
| [Moyen terme](#moyen-terme--fonctionnalités-v030) | Profils horaires, déclencheurs solaires, multi-instance | quelques jours par lot |
| [Long terme](#long-terme--stabilisation-v10) | Templates, notifications, statistiques, API publique stabilisée | plusieurs semaines |
| [Pistes exploratoires](#pistes-exploratoires) | Météo, luminosité, jours fériés, ouverture partielle | à évaluer au cas par cas |

---

## Statut actuel

La version courante est **v0.2.4**. Pour la liste des fonctionnalités
déjà disponibles, voir la section [Fonctionnalités](README.md#fonctionnalités)
du README. Pour l'historique détaillé des versions livrées, voir le
[CHANGELOG.md](CHANGELOG.md).

Le présent document décrit uniquement les évolutions **à venir**.

---

## Moyen terme — fonctionnalités v0.3.0

### 1. Déclencheurs solaires

**Motivation.** Beaucoup d'utilisateurs préfèrent piloter leurs volets
relativement au coucher ou au lever du soleil plutôt qu'à une heure
fixe. L'horaire fixe désynchronise les volets et la luminosité réelle
au fil des saisons (jusqu'à plus de 4 h d'écart entre les solstices à
nos latitudes).

**Piste technique.** Réutiliser
`homeassistant.helpers.sun.get_astral_event_next` pour calculer
sunrise/sunset. Étendre le `config_flow` avec un sélecteur (« heure
fixe » / « relatif au lever » / « relatif au coucher ») et un offset
signé (+/- minutes). Conserver le décalage aléatoire en plus du
décalage solaire.

### 2. Profils horaires

**Motivation.** Aujourd'hui une seule paire (`open_time`,
`close_time`) + une liste de jours actifs. Pas de différenciation
semaine / week-end ; pas de mode vacances activable temporairement.
Les utilisateurs qui veulent ces différences doivent dupliquer
manuellement leurs automations ou attendre.

**Piste technique.** Plusieurs profils nommés (« Semaine »,
« Week-end », « Vacances ») dans le `config_flow`, chacun avec son
couple horaire et ses jours. Un seul profil actif à la fois,
sélection via un nouveau `select.shutters_management_profile` ou un
`input_boolean.vacances` exposé par l'utilisateur. La logique du
scheduler résout le profil actif à chaque déclenchement.

### 3. Multi-instance

**Motivation.** Une seule entrée du domaine est aujourd'hui autorisée
(`async_set_unique_id(DOMAIN)` puis
`_abort_if_unique_id_configured()` dans `config_flow.py`). Or
beaucoup d'utilisateurs ont plusieurs zones (étage / RDC / garage /
résidence secondaire) avec des horaires distincts.

**Piste technique.** Retirer l'abort unique dans `async_step_user` ;
dériver l'`unique_id` du config_entry de l'`entry_id` lui-même. Les
`unique_id` des entités sont déjà préfixés par `entry.entry_id`
(depuis v0.2.1) — pas de migration nécessaire. Scoper
`SIGNAL_STATE_UPDATE` par `entry_id` pour éviter les rafraîchissements
croisés. Adapter les services `run_now` / `pause` / `resume` pour
accepter un `target` (device_id ou entity_id), avec broadcast par
défaut pour rétro-compatibilité. Les tests v0.2.2 ont été conçus
pour survivre à ce refactor (~95 % de réutilisation prévue).

### 4. Réglages avancés du décalage aléatoire

**Motivation.** Aujourd'hui le décalage est tiré uniformément dans
`[0, random_max_minutes]`. Une distribution gaussienne centrée
donnerait un comportement plus naturel (la majorité des
déclenchements proches de l'heure programmée, queue de distribution
rare). Et le tirage est ré-évalué à chaque déclenchement : impossible
de figer un décalage hebdomadaire pour reproduire un rythme.

**Piste technique.** Sélecteur dans le `config_flow` : « uniforme »
(actuel) / « gaussienne » (`random.gauss(0, sigma)` clippé) /
« figé » (décalage choisi à la création de l'entrée et persisté). Le
module `random` de la stdlib suffit ; pas de nouvelle dépendance.

---

## Long terme — stabilisation v1.0.0

### 5. Support natif des `group.*` de type cover

**Motivation.** Un utilisateur qui veut piloter « tous les volets du
RDC » regroupe ses entités dans un `group.volets_rdc` puis sélectionne
ce groupe dans le `config_flow`. Aujourd'hui le selector n'accepte que
des `cover.*` directes : il faut lister chaque membre, et toute
modification du groupe oblige à éditer la config de l'intégration.

**Piste technique.** Ajouter `domain=["cover", "group"]` au
`EntitySelectorConfig` du `config_flow` ; au moment du `_async_call`,
résoudre les membres récursivement via `expand_entity_ids` du helper
`group`.

### 6. Templates Jinja dans les heures

**Motivation.** Permettre à l'utilisateur d'utiliser
`{{ states('input_datetime.shutter_open') }}` ou tout autre helper HA
comme source d'horaire, plutôt que de figer une valeur dans la
config. Ouvre la porte à des automations externes qui modifient les
horaires sans toucher à l'options flow de l'intégration.

**Piste technique.** Stocker la valeur sous forme de chaîne et
l'évaluer via `Template(...).async_render()` à chaque calcul de
`next_open` / `next_close`. Validation côté `config_flow` via
`cv.template`. Garder la rétro-compatibilité : une valeur sans
`{{` reste interprétée comme un littéral `HH:MM:SS`.

### 7. Notifications optionnelles

**Motivation.** Un utilisateur peut vouloir être notifié quand
l'intégration ouvre ou ferme ses volets, surtout en mode absence
(« quelqu'un — l'intégration — vient d'agir sur la maison »).
Aujourd'hui aucune notification native ; il faut composer avec une
automatisation externe sur le `switch.*_simulation_active` ou les
`sensor.*_next_*`.

**Piste technique.** Champ optionnel dans le `config_flow` : nom du
service `notify.*` à appeler. Au moment du déclenchement, appeler le
service avec un message paramétrable
(`{{ action }}` / `{{ covers }}`). Option « avant », « après » ou
« avant et après ».

### 8. Statistiques d'exécution

**Motivation.** Aucun moyen aujourd'hui de répondre à « combien de
fois l'intégration a-t-elle déclenché cette semaine ? » ou « quelle
est la dernière action exécutée sur ces volets ? » sans plonger dans
les logs Home Assistant.

**Piste technique.** Nouveaux capteurs : `sensor.*_last_action`
(timestamp + attributs `action` / `covers`) et compteur
`sensor.*_total_runs` cumulé, persisté via `RestoreEntity`. Le graphe
historique sur 30 jours est ensuite obtenu gratuitement via la
History UI standard de Home Assistant.

### 9. Tableau de bord Lovelace dédié

**Motivation.** L'utilisateur doit aujourd'hui composer manuellement
sa carte (cf. exemple du README). Une carte Lovelace personnalisée
fournirait directement un widget complet avec switch, boutons et
prochains déclenchements, gain de productivité pour les nouveaux
utilisateurs.

**Piste technique.** Carte `custom-element` TypeScript (HACS frontend
plugin) packagée dans un repo séparé `shutters_management-card`, avec
un `dist/` chargé via `/local/`. Permettrait aussi un mode « édition
des horaires depuis le dashboard » via les services `pause` /
`resume` / `run_now` exposés.

### 10. Stabilisation de l'API publique

**Motivation.** La sémantique des services, des entités exposées et
du schéma de configuration doit être garantie pour que les
utilisateurs puissent compter dessus dans leurs automations à long
terme. Tout changement breaking est aujourd'hui possible (cf. v0.2.1
qui a remplacé `binary_sensor` par `switch`).

**Piste technique.** Documenter formellement chaque service et
chaque entité dans le README ; figer les `unique_id` (déjà fait
depuis v0.2.1) et les noms de services. Politique stricte de
breaking changes : pas sans bump de version majeure et, lorsque
possible, migration automatique via `async_migrate_entry`.

---

## Pistes exploratoires

Idées à évaluer au cas par cas, sans priorité ferme.

### Capteurs externes

- **Capteur météo** : adapter l'heure d'ouverture/fermeture selon
  l'ensoleillement (fermeture anticipée par ciel couvert, retardée
  par ciel clair) ou la température extérieure (fermeture précoce
  l'hiver pour conserver la chaleur).
- **Capteur de luminosité** : déclenchement sur seuil lux plutôt
  qu'horaire, en complément ou substitution. À combiner avec les
  déclencheurs solaires de l'item 1.

### Logique fine

- **Ouverture partielle** via `cover.set_cover_position` : utile pour
  les fenêtres de toit ou les volets à lamelles inclinables.
- **Mode « vacances longues »** : randomisation plus large et
  asymétrique entre ouverture et fermeture, pour brouiller davantage
  les routines détectables. À envisager comme un profil dédié
  (cf. item 2).

### Calendriers

- **Calendrier de jours fériés** (France initialement, configurable
  par pays via [`python-holidays`](https://pypi.org/project/holidays/)) :
  le profil semaine ne s'applique pas les jours fériés. À combiner
  avec les profils horaires de l'item 2.

---

## Contribuer à cette feuille de route

Les priorités évoluent avec les retours utilisateurs. Si une
évolution vous intéresse — ou si vous en voyez une qui manque —
ouvrez d'abord une **issue** décrivant le besoin et la solution
envisagée, puis proposez une pull request thématique depuis une
branche `feat/...` basée sur `main`.

Suivez les conventions du dépôt : sujet de commit court à
l'impératif, message expliquant le **pourquoi** plutôt que le
**quoi**. Pour les évolutions touchant le `config_flow`, mettez à
jour `strings.json` et les fichiers `translations/*.json` (`en.json`
et `fr.json`). Lancez localement `pytest` et
`python3 -m py_compile` sur les fichiers modifiés avant push.
