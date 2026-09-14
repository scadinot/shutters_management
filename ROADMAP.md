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
| [Statut actuel](#statut-actuel) | Version courante v0.9.27 — voir CHANGELOG pour l'historique | livré |
| [Court terme](#court-terme--dette-technique) | Découpage de `__init__.py`, chargement de la carte 3D, ciblage des services par sous-entrée | quelques jours par lot |
| [Moyen terme](#moyen-terme--prochaines-versions) | Profils horaires, réglages avancés du décalage aléatoire | quelques jours par lot |
| [Long terme](#long-terme--stabilisation-v100) | Groupes de volets, templates Jinja, statistiques d'exécution, API publique stabilisée | plusieurs semaines |
| [Pistes exploratoires](#pistes-exploratoires) | Météo, jours fériés, réglages fins de la protection solaire, notifications avancées | à évaluer au cas par cas |

---

## Statut actuel

La version courante est **v0.9.27**. Pour la liste des fonctionnalités
déjà disponibles, voir la section [Fonctionnalités](README.md#fonctionnalités)
du README. Pour l'historique détaillé des versions livrées, voir le
[CHANGELOG.md](CHANGELOG.md).

Faits marquants depuis v0.7.1 :

- **v0.8.0** — tableau de bord intégré : panneau « Shutters Management »
  dans la barre latérale, vue cockpit et vue détaillée par
  sous-entrée, reconstruits automatiquement à chaque modification.
- **v0.9.0** — carte Lovelace `custom:shutters-sun-3d-card` (Three.js)
  servie par l'intégration : position du soleil et arc de la façade
  en 3D.
- **v0.9.10 → v0.9.13** — carte « État de la décision » : statut
  courant, conditions de fermeture détaillées, voyant coloré par
  critère.
- **v0.9.20** — mode séquentiel : volet suivant lancé dès 50 % de
  course du volet en cours.
- **v0.9.21** — une erreur sur un volet n'interrompt plus la séquence ;
  capteurs « Prochaine ouverture / fermeture » rafraîchis même quand
  un déclenchement est ignoré.
- **v0.9.22** — l'état survit aux redémarrages de Home Assistant
  (pause, switch de protection solaire, mode soleil et positions
  mémorisées, override), dans `.storage/shutters_management.state`.
- **v0.9.23** — un rechargement de l'intégration ne rouvre plus les
  volets en mode soleil ; plus de manager orphelin après suppression
  d'une sous-entrée.
- **v0.9.24** — sortie du mode soleil sur l'UV temporisée (20 min).
- **v0.9.25** — réévaluation de la protection solaire à l'expiration
  de chaque debounce.
- **v0.9.26** — tolérance de ±3 points sur la position des volets
  (restauration et détection des mouvements manuels).
- **v0.9.27** — seuils du panneau lus depuis `const.py`.

Le présent document décrit uniquement les évolutions **à venir**.

---

## Court terme — dette technique

### T1. Découpage de `__init__.py`

**Motivation.** `__init__.py` dépasse 2 000 lignes et mélange des
responsabilités indépendantes : migrations v2 → v8, notifications et
TTS, services, planificateur, moteur de protection solaire,
persistance et enregistrement du frontend. Les revues et les
évolutions de la protection solaire en sont plus lentes, et chaque
PR touche le même fichier.

**Piste technique.** Déplacer le code sans changer le comportement
dans des modules dédiés : `scheduler.py` (`ShuttersScheduler`),
`sun_protection.py` (`ShuttersSunProtectionManager` et restauration
des positions), `notifications.py`, `migrations.py`. `__init__.py` ne
garde que le cycle de vie de l'entrée (setup, unload, remove,
services). Attention aux tests qui patchent des symboles par leur
chemin (`custom_components.shutters_management.random.shuffle`,
`…async_call_later`) : ils devront viser le nouveau module, dans la
même PR.

### T2. Chargement de la carte 3D à la demande

**Motivation.** La carte est enregistrée via
`frontend.add_extra_js_url` : son module et Three.js (~670 Ko) sont
chargés sur **toutes** les pages du frontend Home Assistant, même
quand la carte n'est affichée nulle part.

**Piste technique.** Garder un module d'enregistrement léger qui ne
définit que l'élément personnalisé, et charger Three.js et
OrbitControls par `import()` dynamique au premier rendu de la carte.

### T3. Ciblage des services par sous-entrée

**Motivation.** Les services `run_now` / `pause` / `resume`
s'appliquent à **toutes** les planifications et simulations (mode
broadcast). Impossible, par exemple, de mettre en pause uniquement
la simulation de présence depuis une automatisation sans passer par
son switch.

**Piste technique.** Accepter une cible (`entity_id` du switch
`simulation_active` ou `device_id` de la sous-entrée) et résoudre les
sous-entrées concernées via `async_extract_referenced_entity_ids` ;
sans cible, conserver le broadcast actuel pour ne rien casser.

---

## Moyen terme — prochaines versions

### 1. Déclencheurs solaires — ✅ livré en v0.3.1

Chaque événement (ouverture / fermeture) peut être configuré en mode
`fixed`, `sunrise` ou `sunset` avec un offset signé en minutes
(-360..+360). Le décalage aléatoire reste appliqué en plus du
décalage solaire. Depuis v0.3.2, le config flow présente tous les
champs dans un **panneau unique** avec deux sections « Ouverture »
et « Fermeture » regroupant chacune `mode`, `time` et `offset` ; le
scheduler ignore au runtime le champ qui ne correspond pas au mode
actif. Voir le [CHANGELOG](CHANGELOG.md#031--2026-04-28).

### 2. Profils horaires

**Motivation.** Aujourd'hui une seule paire (`open_time`,
`close_time`) + une liste de jours actifs. Pas de différenciation
semaine / week-end ; pas de mode vacances activable temporairement.
Les utilisateurs qui veulent ces différences doivent dupliquer
manuellement leurs sous-entrées ou leurs automations.

**Piste technique.** Plusieurs profils nommés (« Semaine »,
« Week-end », « Vacances ») dans le `config_flow`, chacun avec son
couple horaire et ses jours. Un seul profil actif à la fois,
sélection via un nouveau `select.<nom>_profile` ou un
`input_boolean.vacances` exposé par l'utilisateur. La logique du
scheduler résout le profil actif à chaque déclenchement.

### 3. Multi-instance — ✅ livré en v0.3.0, remplacé par le hub en v0.4.0

Plusieurs groupes indépendants de volets coexistent. Depuis v0.4.0,
ils prennent la forme de **sous-entrées** d'un hub unique (voir
item 7), chacune avec son device et ses entités. Voir le
[CHANGELOG](CHANGELOG.md#030--2026-04-27).

Le ciblage des services par sous-entrée est suivi dans
[T3](#t3-ciblage-des-services-par-sous-entrée).

### 4. Réglages avancés du décalage aléatoire

**Motivation.** Aujourd'hui le décalage est tiré uniformément dans
`[0, random_max_minutes]`. Une distribution gaussienne centrée
donnerait un comportement plus naturel (la majorité des
déclenchements proches de l'heure programmée, queue de distribution
rare). Et le tirage est ré-évalué à chaque déclenchement : impossible
de figer un décalage hebdomadaire pour reproduire un rythme.

**Piste technique.** Sélecteur dans le `config_flow` : « uniforme »
(actuel) / « gaussienne » (`random.gauss(0, sigma)` clippé) /
« figé » (décalage choisi à la création de la sous-entrée et
persisté dans le `ShuttersStateStore` introduit en v0.9.22). Le
module `random` de la stdlib suffit ; pas de nouvelle dépendance.

---

## Long terme — stabilisation v1.0.0

### 5. Support natif des `group.*` de type cover

**Motivation.** Un utilisateur qui veut piloter « tous les volets du
RDC » regroupe ses entités dans un `group.volets_rdc` puis voudrait
sélectionner ce groupe dans le `config_flow`. Aujourd'hui le sélecteur
n'accepte que des `cover.*` directes : il faut lister chaque membre, et
toute modification du groupe oblige à reconfigurer la sous-entrée.

**Piste technique.** Ajouter `domain=["cover", "group"]` au
`EntitySelectorConfig` du `config_flow` ; au moment de l'action,
résoudre les membres récursivement via `expand_entity_ids` du helper
`group`. Pour la protection solaire, les positions doivent être
mémorisées et restaurées par volet membre, pas par groupe.

### 6. Templates Jinja dans les heures

**Motivation.** Permettre à l'utilisateur d'utiliser
`{{ states('input_datetime.shutter_open') }}` ou tout autre helper HA
comme source d'horaire, plutôt que de figer une valeur dans la
config. Ouvre la porte à des automations externes qui modifient les
horaires sans reconfigurer la sous-entrée.

**Piste technique.** Stocker la valeur sous forme de chaîne et
l'évaluer via `Template(...).async_render()` à chaque calcul de
`next_open` / `next_close`. Validation côté `config_flow` via
`cv.template`. Garder la rétro-compatibilité : une valeur sans
`{{` reste interprétée comme un littéral `HH:MM:SS`.

### 7. Notifications optionnelles — ✅ livré en v0.4.0, étendu en v0.7.0

Multi-select des services `notify.*` au niveau du **hub**, plus deux
modes par **sous-entrée** depuis v0.7.0 :
- `notify_mode` : `disabled` / `always` / `away_only`.
- `tts_mode` : `disabled` / `always` / `home_only`.

Annonces vocales TTS sur les `media_player.*` configurés au hub
depuis v0.4.3. Notifications côté Sun Protection depuis v0.7.0
(ouvertures et fermetures automatiques). Messages localisés FR/EN,
une notification cassée ne bloque jamais l'action sur les volets.
Depuis v0.9.21, en mode séquentiel, la notification ne liste que les
volets réellement actionnés. Voir les CHANGELOG
[v0.4.0](CHANGELOG.md#040--2026-05-01),
[v0.4.3](CHANGELOG.md#043--2026-05-01) et
[v0.7.0](CHANGELOG.md#070--2026-05-04).

L'architecture **hub + sous-entrées** introduite en v0.4.0 (pattern
`ConfigSubentryFlow` de HA 2025.3+) est désormais le format
canonique. La chaîne de migration automatique va de v2 (legacy
mono-entry) à v8 (présence multi-entités), chaque étape
préservant les `entity_id` et `unique_id` existants.

Pas couvert (reportés) : personnalisation Jinja du message,
notification avant l'action, notification sur pause/resume, ciblage
des services notify par sous-entrée.

### 8. Statistiques d'exécution

**Motivation.** Aucun moyen aujourd'hui de répondre à « combien de
fois l'intégration a-t-elle déclenché cette semaine ? » ou « quelle
est la dernière action exécutée sur ces volets ? » sans plonger dans
les logs Home Assistant.

**Piste technique.** Nouveaux capteurs : `sensor.*_last_action`
(timestamp + attributs `action` / `covers`) et compteur
`sensor.*_total_runs` cumulé, persisté dans le `ShuttersStateStore`
(v0.9.22) plutôt que via `RestoreEntity`. Le graphe historique sur
30 jours est ensuite obtenu gratuitement via la History UI standard
de Home Assistant.

### 9. Tableau de bord Lovelace dédié — ✅ livré en v0.8.0 et v0.9.0

Plutôt qu'une carte packagée dans un dépôt séparé, l'intégration
génère elle-même un **panneau « Shutters Management »** dans la barre
latérale (v0.8.0) : vue cockpit listant toutes les sous-entrées, puis
une vue détaillée par sous-entrée (prochains déclenchements, volets
pilotés, boutons de test ; pour la protection solaire : état de la
décision, jauges de marges, historique). La carte
`custom:shutters-sun-3d-card` (v0.9.0) visualise en 3D la position du
soleil face à la façade. Voir les CHANGELOG
[v0.8.0](CHANGELOG.md#080--2026-05-05) et
[v0.9.0](CHANGELOG.md#090--2026-05-06).

Pas couvert : édition des horaires directement depuis le tableau de
bord.

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
possible, migration automatique via `async_migrate_entry`. La
chaîne actuelle va jusqu'à `ENTRY_VERSION = 8` (cf. v0.7.1) et
chaque palier est couvert par un test dédié dans
`tests/test_migration.py`. Le format du document persisté
`.storage/shutters_management.state` (v0.9.22, `STORAGE_VERSION = 1`)
fait aussi partie du contrat : toute évolution passe par une montée
de `STORAGE_VERSION` avec migration.

---

## Pistes exploratoires

Idées à évaluer au cas par cas, sans priorité ferme.

### Capteurs externes

- **Capteur météo** : adapter l'heure d'ouverture/fermeture selon
  l'ensoleillement (fermeture anticipée par ciel couvert, retardée
  par ciel clair) ou la température extérieure (fermeture précoce
  l'hiver pour conserver la chaleur).
- **Capteur de luminosité** : déjà utilisé par la protection solaire
  depuis v0.6.0 (lux et UV). Reste à évaluer comme déclencheur des
  planifications, en complément ou substitution de l'horaire, à
  combiner avec les déclencheurs solaires de l'item 1.

### Logique fine

- **Ouverture partielle** via `cover.set_cover_position` : déjà
  utilisée par la protection solaire (position cible configurable).
  Reste à proposer pour les planifications, utile pour les fenêtres
  de toit ou les volets à lamelles inclinables.
- **Mode « vacances longues »** : randomisation plus large et
  asymétrique entre ouverture et fermeture, pour brouiller davantage
  les routines détectables. À envisager comme un profil dédié
  (cf. item 2).

### Protection solaire

- **Hystérésis sur l'indice UV** : sortie du mode soleil sous
  `min_uv - 1` plutôt que sous `min_uv`, en complément du debounce
  de 20 min (v0.9.24), pour les indices qui oscillent autour du seuil.
- **Réglages exposés dans le `config_flow`** : durées de debounce,
  hystérésis et tolérance de position (`POSITION_TOLERANCE_PCT`) sont
  aujourd'hui des constantes. Les rendre configurables par groupe
  seulement si des retours utilisateurs le justifient.

### Calendriers

- **Calendrier de jours fériés** (France initialement, configurable
  par pays via [`python-holidays`](https://pypi.org/project/holidays/)) :
  le profil semaine ne s'applique pas les jours fériés. À combiner
  avec les profils horaires de l'item 2.

### Notifications avancées

- **Notification sur pause / resume** d'une sous-entrée (aujourd'hui
  uniquement sur open / close).
- **Personnalisation Jinja** du titre et du corps de la notification
  / annonce vocale, avec accès à `subentry.title`, `action`, liste
  des covers, état de présence.

---

## Contribuer à cette feuille de route

Les priorités évoluent avec les retours utilisateurs. Si une
évolution vous intéresse — ou si vous en voyez une qui manque —
ouvrez d'abord une **issue** décrivant le besoin et la solution
envisagée, puis proposez une pull request thématique depuis une
branche basée sur `main`.

Suivez les conventions du dépôt : sujet de commit court à
l'impératif, message expliquant le **pourquoi** plutôt que le
**quoi**. Chaque PR fonctionnelle incrémente la version dans
`manifest.json` et ajoute son entrée au [CHANGELOG.md](CHANGELOG.md).
Pour les évolutions touchant le `config_flow`, mettez à jour
`strings.json` et les fichiers `translations/*.json` (`en.json` et
`fr.json`). La CI exécute `pytest` sous Python 3.13 (requis par Home
Assistant 2026.3+) ainsi que les validations HACS et Hassfest ; lancez
localement `pytest` et `python3 -m py_compile` sur les fichiers
modifiés avant push lorsque c'est possible.
