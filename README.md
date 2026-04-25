# Shutters Management

Custom integration Home Assistant (HACS) pour simuler une présence avec des volets roulants.

## Fonctionnalités

- Configuration via UI (`config_flow`).
- Sélection de plusieurs volets (`cover.*`).
- Horaires d'ouverture et de fermeture.
- Jours actifs configurables.
- Décalage aléatoire (en minutes) pour éviter des horaires fixes.
- Option pour exécuter uniquement quand le foyer est absent.

## Installation via HACS (Custom repository)

1. Ouvrir HACS > Integrations > menu ⋮ > Custom repositories.
2. Ajouter l'URL du repo GitHub.
3. Type: **Integration**.
4. Installer puis redémarrer Home Assistant.
5. Ajouter l'intégration **Shutters Management** depuis Paramètres > Appareils et services.

## Configuration

L'intégration propose un assistant de configuration UI avec :

- Volets à piloter.
- Heure d'ouverture.
- Heure de fermeture.
- Jours actifs.
- Activation de l'aléatoire + amplitude max.
- Exécution uniquement en absence (optionnel).
