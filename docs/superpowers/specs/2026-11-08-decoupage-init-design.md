# Découpage de `__init__.py` — design

- **Date** : 2026-11-08
- **Item de la feuille de route** : T1 (dette technique, court terme)
- **Version cible** : 0.9.28
- **Nature** : déplacement pur, aucun changement de comportement

## Problème

`custom_components/shutters_management/__init__.py` fait **2 278 lignes** et
mélange sept responsabilités indépendantes :

| Bloc | Lignes |
|---|---|
| `ShuttersSunProtectionManager` | 785 |
| `ShuttersScheduler` | 498 |
| Notifications, TTS et leurs helpers | 276 |
| Chaîne de migration v2 → v8 | 255 |
| Cycle de vie de l'entrée | 160 |
| Helpers de position des volets | 69 |
| Services et enregistrement du frontend | 78 |

Conséquences observées : chaque pull request touche le même fichier, les revues
sont lentes, et les deux chantiers suivants de la feuille de route (T2 carte 3D,
T3 ciblage des services) viendraient encore y ajouter du code.

## Intention et critères de réussite

L'objectif est la **maintenabilité**, pas un changement visible par
l'utilisateur. Le refactor est réussi si, et seulement si :

1. Chaque module a un objet unique et énonçable en une phrase.
2. Aucun comportement ne change : mêmes entités, mêmes services, même état
   persisté, mêmes messages.
3. Les 190+ tests passent sans modification de leur **logique**.
4. L'intégration charge sur une installation réelle, avec ses 5 sous-entrées
   intactes.

Ce qui invaliderait le refactor : un seul test en échec, ou une modification de
logique au-delà des déplacements. Dans ce cas on corrige ou on abandonne
l'étape — on n'adapte pas un test pour le faire passer.

## Contraintes

- **Déplacement pur** : aucun renommage, aucune réécriture, aucune optimisation
  au passage.
- **Pas de cycle d'imports** : c'est le risque numéro un, il se manifesterait en
  production par « l'intégration ne charge pas ».
- La suite de tests ne peut pas s'exécuter sous Windows : `homeassistant/runner.py`
  importe `fcntl`, exclusif à Unix. La vérification locale se limite donc à un
  contrôle d'imports ; la suite complète tourne sur la CI.

## Architecture retenue

Graphe de dépendances, chaque flèche allant du module vers ce qu'il importe.
Aucun cycle :

```
const.py ................ feuille, n'importe rien du paquet
entities.py ............. feuille
state_store.py .......... const
presence.py ............. const
notifications.py ........ const, presence
scheduler.py ............ const, presence, notifications, state_store
sun_protection.py ....... const, notifications, state_store
migrations.py ........... const
services.py ............. const, scheduler
frontend.py ............. const
panel.py ................ const                        (inchangé)
__init__.py ............. tous les précédents
switch / sensor / binary_sensor / button
                      ... const, entities, scheduler, sun_protection
```

Deux règles garantissent l'acyclicité :

- **aucun module métier n'importe `__init__.py`** ;
- les plateformes importent `.scheduler` / `.sun_protection` directement, au lieu
  de `from . import`.

Tailles visées :

| Module | ~lignes | Objet |
|---|---|---|
| `__init__.py` | 200 | Cycle de vie de l'entrée |
| `sun_protection.py` | 860 | Moteur de protection solaire |
| `scheduler.py` | 540 | Planification et exécution sur les volets |
| `migrations.py` | 260 | Montée de version des données |
| `notifications.py` | 250 | Push et annonces vocales |
| `presence.py` | 50 | Présence du foyer |
| `services.py` | 45 | Services de l'intégration |
| `frontend.py` | 40 | Ressources statiques et carte 3D |

## Répartition des symboles

| Destination | Symboles déplacés |
|---|---|
| `sun_protection.py` | `ShuttersSunProtectionManager`, `_async_restore_cover_positions`, `_position_matches`, `_restored_positions` |
| `scheduler.py` | `ShuttersScheduler`, `_parse_time`, `_next_datetime_for` |
| `migrations.py` | `async_migrate_entry`, `_async_migrate_legacy_entries`, `_strip_name` |
| `notifications.py` | `_async_dispatch_notifications`, `_async_send_push`, `_async_send_tts`, `_notify_message`, `_tts_message`, `_cover_display_name`, `_NOTIFY_HEADERS`, `_TTS_HEADERS` |
| `presence.py` | `_is_away_for` |
| `services.py` | `RUN_NOW_SCHEMA`, `_async_register_services`, `_async_unregister_services` |
| `frontend.py` | `_async_register_frontend_resources`, `_FRONTEND_DIR`, `_FRONTEND_URL`, `_CARD_URL`, `_FRONTEND_REGISTERED_FLAG` |

`__init__.py` conserve `CONFIG_SCHEMA`, `_STATE_STORE_KEY`,
`_RESIDUAL_DEVICE_MODELS`, `async_setup`, `async_setup_entry`,
`async_unload_entry`, `async_remove_entry` et `_async_update_listener`.

## Décisions de conception

**Aucun renommage.** Les helpers gardent leur underscore initial, même devenus
inter-modules. La convention voudrait qu'on les renomme, mais un déplacement pur
se relit ; un déplacement plus renommage, non. Un passage cosmétique reste
possible plus tard.

**`__init__.py` ré-exporte quatre noms** : `ShuttersScheduler`,
`ShuttersSunProtectionManager`, `_async_restore_cover_positions` et
`async_migrate_entry`. Les deux premiers y sont de toute façon importés pour le
cycle de vie. Le quatrième est obligatoire : Home Assistant cherche
`async_migrate_entry` sur le module de l'intégration. Conséquence utile : les
cinq fichiers de tests qui importent depuis le paquet ne changent pas d'une
ligne.

**`presence.py` existe comme module à part** parce que `_is_away_for` sert aux
notifications **et** au planificateur. Le placer dans `notifications.py`
obligerait le planificateur à importer les notifications juste pour savoir si la
maison est vide.

**Nommer un module `frontend.py` ne masque pas `homeassistant.components.frontend`** :
Python 3 utilise les imports absolus, les deux coexistent sans ambiguïté. Vérifié
avant de retenir ce nom.

**`sun_protection.py` reste à 860 lignes.** Découper la classe elle-même, par
exemple séparer le moteur de décision de la commande des volets, est un autre
exercice, avec un vrai risque de comportement. Hors périmètre, à inscrire dans la
feuille de route.

## Impact sur les tests

Les 5 imports depuis le paquet ne bougent pas. **18 cibles de `patch()`** doivent
être réécrites : patcher un nom dans `__init__` ne patche pas celui qu'un autre
module a importé.

| Nouvelle cible | Sites | Fichiers |
|---|---|---|
| `…shutters_management.scheduler.random.shuffle` | 9 | `test_sequential_covers` (8), `test_notifications` (1) |
| `…scheduler.get_astral_event_next` | 3 | `test_sun_trigger` |
| `…scheduler.async_track_time_change` / `_sunrise` / `_sunset` | 3 | `test_sun_trigger` |
| `…scheduler.async_dispatcher_send` | 1 | `test_multi_instance` |
| `…scheduler.COVER_ACTION_TIMEOUT_SECONDS` | 1 | `test_sequential_covers` |
| `…sun_protection.async_call_later` | 1 | `test_sun_protection`, constante `_CALL_LATER` |

Les 25 cibles vers `.const` et les 2 vers `.panel` restent valides.

La pull request doit pouvoir affirmer : *aucune logique de test modifiée,
uniquement des chaînes de cible*. Preuve attendue dans la description : un diff
filtré des tests ne laissant apparaître que ces 18 lignes.

## Ordre de travail

Déplacement de bas en haut du graphe, avec contrôle d'imports après **chaque**
étape ; à chaque palier le paquet doit rester importable :

`presence` → `notifications` → `sun_protection` → `scheduler` → `migrations` →
`services` → `frontend` → allègement d'`__init__.py` → plateformes → tests.

## Vérification

1. **Contrôle d'imports local**, après chaque étape : charge tous les modules du
   paquet et vérifie les ré-exports. Détecte boucles et symboles manquants en une
   seconde.
2. **CI sur la pull request** : 190+ tests sur Python 3.13, plus HACS et Hassfest.
3. **Production**, après merge et release : installation HACS, redémarrage,
   vérification que l'intégration charge, que les 5 sous-entrées sont présentes et
   que switches et capteurs ont survécu — ce qui teste aussi la relecture de
   `.storage`.

## Livraison

Une seule pull request. Version **0.9.28** avec une entrée CHANGELOG
« Modifié — découpage interne, aucun changement de comportement ». Sont inclus :
l'arborescence du README, l'item T1 de la feuille de route marqué livré, et
`.venv/` dans le `.gitignore`.

## Hors périmètre

- Découpage de `panel.py` (1 572 lignes) et de `config_flow.py` (1 138 lignes).
- Découpage interne de `ShuttersSunProtectionManager`.
- Renommage des helpers privés devenus inter-modules.
- T2, chargement à la demande de la carte 3D, et T3, ciblage des services, qui
  viendront ensuite se ranger dans `frontend.py` et `services.py`.

## Alternatives écartées

**Découpage médian, 4 modules** : `scheduler`, `sun_protection`, `notifications`
et `migrations`, le reste restant dans `__init__.py`. Même bénéfice principal et
diff légèrement plus petit, mais T2 et T3 rouvriraient `__init__.py` et le
feraient regrossir. On referait ce travail dans six mois.

**Découpage minimal, 2 modules** : les deux grosses classes seulement. Plus petit
risque, mais `__init__.py` resterait à environ 1 000 lignes avec migrations et
notifications mêlées au cycle de vie. Ne règle pas le problème.
