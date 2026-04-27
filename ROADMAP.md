# Roadmap — Shutters Management

Ce document liste les évolutions envisagées pour l'intégration. Il est indicatif : l'ordre et le contenu de chaque jalon peuvent évoluer en fonction des retours et des contributions.

## Vision

Offrir une intégration Home Assistant simple, fiable et entièrement configurable graphiquement pour simuler une présence en pilotant des volets roulants. La priorité est la robustesse en production, puis la richesse fonctionnelle (profils, déclencheurs solaires, observabilité), avant d'envisager des extensions plus avancées (templates, statistiques).

## Statut actuel

La version courante est **v0.2.3**. Pour la liste des fonctionnalités déjà disponibles, voir la section [Fonctionnalités](README.md#fonctionnalités) du README. Pour l'historique détaillé des versions livrées, voir le [CHANGELOG.md](CHANGELOG.md).

Le présent document décrit uniquement les évolutions **à venir**.

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
