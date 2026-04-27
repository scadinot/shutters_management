# Roadmap — Shutters Management

Ce document liste les évolutions envisagées pour l'intégration. Il est indicatif : l'ordre et le contenu de chaque jalon peuvent évoluer en fonction des retours et des contributions.

## Vision

Offrir une intégration Home Assistant simple, fiable et entièrement configurable graphiquement pour simuler une présence en pilotant des volets roulants. La priorité est la robustesse en production, puis la richesse fonctionnelle (profils, déclencheurs solaires, observabilité), avant d'envisager des extensions plus avancées (templates, statistiques).

## Statut actuel — v0.2.1

Livré :

- Configuration entièrement par interface graphique (`config_flow` + `OptionsFlow`).
- Sélection multiple d'entités `cover.*`.
- Heures d'ouverture et de fermeture indépendantes, en heure locale.
- Choix des jours actifs (lun – dim).
- Décalage aléatoire optionnel, plafonné avant minuit.
- Mode « uniquement en absence » avec entité de présence explicite ou repli sur les `person.*`.
- Ré-évaluation des conditions au moment de l'exécution différée.
- Annulation propre des déclencheurs et des callbacks différés au déchargement / rechargement.
- Traductions français et anglais.

## v0.2.0 — Livré

Objectif : combler les manques d'observabilité et faciliter l'automatisation.

- **Services Home Assistant exposés** :
  - `shutters_management.run_now` (champ obligatoire `action`) pour forcer un déclenchement immédiat.
  - `shutters_management.pause` / `shutters_management.resume` pour suspendre temporairement la simulation.
- **Entités exposées** :
  - `sensor.shutters_management_next_opening` : horodatage du prochain déclenchement d'ouverture.
  - `sensor.shutters_management_next_closing` : horodatage du prochain déclenchement de fermeture.
  - `binary_sensor.shutters_management_simulation_active` : état actif / en pause de la simulation.
- **Confort d'usage** :
  - Menu d'options avec entrées « Tester ouverture / fermeture » et « Mettre en pause / Reprendre ».
  - Étape de confirmation dans le config_flow si `only_when_away` est coché alors qu'aucune `person.*` ni `presence_entity` n'est disponible.

## v0.2.1 — Livré

Objectif : rendre les actions accessibles directement depuis un tableau de bord Lovelace, sans passer par l'écran d'options.

- **Nouvelles entités actionnables** :
  - `switch.shutters_management_simulation_active` : togglable, expose et contrôle l'état actif/pause de la simulation.
  - `button.shutters_management_test_open` : déclenche immédiatement une ouverture des volets configurés.
  - `button.shutters_management_test_close` : déclenche immédiatement une fermeture.
- **Breaking change** : le `binary_sensor.shutters_management_simulation_active` introduit en v0.2.0 a été remplacé par le switch. Les automations existantes doivent être mises à jour pour pointer vers `switch.shutters_management_simulation_active` (les états restent `on` / `off`).

## v0.2.2 — En attente (qualité)

- **Tests et CI** :
  - Suite de tests unitaires (planification, plafonnement minuit, ré-évaluation, présence, services, sensors, switch, buttons).
  - GitHub Actions : `hassfest`, `HACS validation`, lint Python (`ruff`), vérification JSON des traductions.

## v0.3.0 — Moyen terme

Objectif : rendre la simulation plus naturelle et plus flexible.

- **Déclencheurs solaires** : ouverture et fermeture relatives au lever ou au coucher du soleil, avec un offset configurable (par exemple « 30 min après le coucher »).
- **Profils** : horaires distincts pour la semaine, le week-end et un mode vacances activable. Chaque profil dispose de son propre couple ouverture/fermeture et de ses jours.
- **Multi-instance** : plusieurs configurations indépendantes coexistantes (étage, RDC, garage, maison secondaire). Refonte de l'`unique_id` pour autoriser plus d'une entrée du même domaine.
- **Réglages avancés du décalage** : choix d'une distribution (uniforme, gaussienne) et possibilité de figer un décalage par déclenchement plutôt qu'un tirage à chaud.

## v1.0.0 — Long terme

Objectif : couvrir les besoins avancés et stabiliser une API publique.

- Support natif des entités `group.*` de type cover (résolution automatique des membres).
- Templates Jinja dans les heures d'ouverture / fermeture (`{{ states('input_datetime.shutter_open') }}`).
- Notifications optionnelles via le service `notify` configuré, déclenchées avant et / ou après chaque action.
- Statistiques d'exécution : compteur des déclenchements, dernière action, historique consultable depuis le tableau de bord.
- Tableau de bord Lovelace dédié (carte personnalisée optionnelle).
- Stabilisation de l'API publique : services, entités, schéma de configuration documentés et versionnés.

## Idées non priorisées

Pistes intéressantes, sans calendrier :

- Intégration avec les capteurs météo (lever / fermer plus tôt selon ensoleillement ou température extérieure).
- Action « ouverture partielle » via `cover.set_cover_position`.
- Calendrier de jours fériés français (et configurable par pays) pour ne pas appliquer le profil semaine.
- Mode « vacances longues » avec randomisation plus large et asymétrique entre ouverture et fermeture.
- Intégration avec un capteur de luminosité pour adapter dynamiquement les heures.

## Contribuer

Les contributions sont les bienvenues. Pour proposer une évolution :

1. Ouvrez d'abord une **issue** décrivant le besoin et la solution envisagée — cela évite des allers-retours sur la pull request.
2. Créez une branche thématique à partir de `main` (par exemple `feat/sun-trigger`).
3. Suivez les conventions de commit déjà en place dans l'historique : sujet court à l'impératif, message expliquant le **pourquoi** plutôt que le **quoi**.
4. Vérifiez que `python3 -m py_compile` passe sur les fichiers modifiés et que les fichiers JSON restent valides.
5. Ouvrez la pull request en référant l'issue correspondante.

Pour les évolutions touchant le `config_flow`, pensez à mettre à jour `strings.json` et les fichiers de `translations/` (au moins `en.json` et `fr.json`).
