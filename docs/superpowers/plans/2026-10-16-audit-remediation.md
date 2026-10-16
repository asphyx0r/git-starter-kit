# Plan de remédiation de F01 à F16

## 1. Objectif, périmètre et invariants

Corriger les 16 observations du tableau, avec une preuve de résolution pour chacune : changement, test, documentation
applicable et résultat de vérification.

Le point de départ vérifié est `e67c9dc`, sur `main`, sans modification visible. L’exécution future commencera sur une
branche dédiée, après un nouvel état des lieux. <!-- codespell:ignore branche -->

Les invariants suivants restent obligatoires :

- Préserver les fichiers personnels, travaux préexistants, historiques publiés et dépôts consommateurs.
- Conserver les dépendances verrouillées, actions figées par SHA, permissions minimales et publication automatique
  existante.
- Maintenir les seuils actuels de couverture : **85 % globalement et 85 % des branches**, sur les périmètres
  actuellement imposés.
- Préserver les snapshots indexés, contrôles des objets poussés, <!-- codespell:ignore objets -->
  délais, restaurations et refus d’écrasement.
- Garder `all`, `full` et `static` exhaustifs, ainsi que les noms des contrôles requis.
- Ne pas ajouter de dépendance, framework, migration ou refactorisation étrangère aux constats.
- Séparer correction locale, qualification hébergée, intégration et publication. Ce plan ne prévoit aucune modification
  des protections GitHub ni publication de release.

Le réemploi contrôlé de qualification pour **F14** est retenu conformément à votre choix.

## 2. Lots de correction et frontières de responsabilité

Chaque lot suit le cycle : **régression reproduite → correction minimale → tests ciblés → documentation synchronisée →
revue**.

| Lot | Constats | Correction arrêtée | Preuves exigées |
| --- | --- | --- | --- |
| **A — Environnement et onboarding** | **F11, F12** | Sélectionner les environnements locaux verrouillés dans la session, sans modifier les installations globales. Retirer les mentions périmées de candidate des guides courants. Préserver les documents historiques datés et les instructions propres aux anciens assets. | Préflight des exécutables réellement sélectionnés réussi ; commandes d’onboarding vérifiées ; absence de configuration globale modifiée. <!-- codespell:ignore environnement,environnements --> |
| **B — Artefacts et packaging** | **F01, F02, F05** | Préparer template, schéma et inventaire depuis la même sélection Git. Pour un packaging SemVer, lire contenus et modes dans `HEAD` ; conserver l’index pour les préversions. Employer les listes Git séparées par NUL. Tenter chaque nettoyage indépendamment et préserver l’erreur initiale. | Index/worktree divergents ; modes uniquement indexés après tag ; chemins Unicode ; refus d’une suppression ; erreurs multiples ; conservation du ZIP final valide après une panne de nettoyage. <!-- codespell:ignore valide --> |
| **C — Mise à niveau et journalisation** | **F03, F04, F10** | Produire un plan exploitable pour un contenu local non UTF-8, sans conversion automatique. Préserver l’erreur métier lorsque le journal échoue et garantir la tentative de fermeture. Clarifier le dry-run : aucune application au dépôt cible, archive, sauvegarde ou journal, mais temporaires de fusion possibles et nettoyés. | Matrice des stratégies ; distinction fichier absent/non décodable ; modifications concurrentes ; pannes du résumé, `flush`, `fsync`, `close` ; dry-run avec fusion réelle et nettoyage. |
| **D — Validation applicative et hooks** | **F06, F07, F13** | Conserver l’encodage texte actuellement sélectionné, avec `errors="backslashreplace"` pour préserver les octets non décodables sous forme échappée. Sélectionner les deux suites d’initialisation pour le helper Python. Charger une seule fois l’ensemble des chemins gérés pour le filtrage des consommateurs. | Diagnostics stdout/stderr non décodables ; codes de sortie inchangés ; deux suites exécutées une seule fois ; fichiers supprimés, espaces et Unicode ; inventaire invalide toujours bloquant. <!-- codespell:ignore espaces,invalide --> |
| **E — Reprise de publication** | **F09** | Comparer les assets distants au payload scellé original avant mutation. Réutiliser les identiques, envoyer les manquants et refuser les différences. Revérifier les trois assets avant promotion. Garder le job privilégié sans checkout et sans exécution de code téléchargé. | Envoi partiel ; promotion échouée puis relance ; digest absent ou incorrect ; asset modifié entre contrôles ; aucun écrasement ni suppression d’un asset valide. <!-- codespell:ignore valide --> |
| **F — Garde-fous et coût des workflows** | **F08, F15, F16** | Vérifier immédiatement les codes natifs après pip et npm sous PowerShell. Passer à `fetch-depth: 1` uniquement pour les deux checkouts de synchronisation et l’agrégateur. Documenter la relance complète de `Repository audit` ; maintenir l’identité stricte des paires de couverture. | Échec pip empêchant npm ; échec npm empêchant le patch ; codes exacts propagés ; transfert depuis clones superficiels ; refus du mélange de tentatives. <!-- codespell:ignore transfert --> |
| **G — Réemploi contrôlé de qualification** | **F14** | Introduire le protocole décrit en section 3, après stabilisation des lots précédents. | Provenance, invalidations, décision commune, repli complet et gains mesurés. <!-- codespell:ignore complet --> |

### Décisions de compatibilité

**F03 — JSON du plan.** Les plans existants valides gardent leur forme. Pour un texte local non UTF-8 uniquement :

- `localCanonicalSha256` vaut `null` ;
- un champ optionnel `localRawSha256` contient l’empreinte brute ;
- l’existence du fichier est déterminée séparément ;
- aucun nouvel état d’action n’est ajouté.

`replace` et `merge` deviennent `conflict-modified`, sans fusion.
`initialize-only` reste préservé ou soumis à revue <!-- codespell:ignore reste -->
selon l’évolution base/cible. Les règles déléguées restent déléguées
; les états JSON invalides deviennent des conflits. <!-- codespell:ignore conflits -->
Les archives et manifestes d’adoption ne changent pas de format.

**F04/F05 — Erreurs secondaires.** Une panne de journal ou de
nettoyage ne remplace jamais la première erreur. Elle <!-- codespell:ignore remplace -->
ajoute un diagnostic contextualisé. Si elle constitue la seule <!-- codespell:ignore constitue -->
panne, l’opération retourne un échec explicite sans <!-- codespell:ignore explicite -->
annoncer une restauration inexistante. <!-- codespell:ignore restauration -->

**F13 — Interface de propriété.** Ajouter une sortie NUL `--list-owned` contenant tous les chemins gérés, y compris
absents. Garder `--owns` et `--list-core` inchangés. Le hook charge
cette liste une fois et utilise des comparaisons <!-- codespell:ignore comparaisons -->
exactes, sans sous-processus par chemin.

**F09 — États distants.**

| État | Comportement |
| --- | --- |
| Asset absent | Envoyer ce fichier uniquement. |
| Asset `uploaded`, taille et SHA identiques | Réutiliser sans écriture. |
| Taille ou SHA différente | Refuser avant toute mutation. |
| Digest absent | Calculer SHA-256 et taille par téléchargement en flux, via l’ID de l’asset. |
| Digest mal formé ou vérification impossible | Refuser. |
| Résidu `starter` vide | Relire et confirmer son état, puis supprimer uniquement cet ID incomplet avant réenvoi. |
| Doublon ou asset inattendu | Refuser sans supprimer. |

Aucun `--clobber`. Une promotion échouée conserve les assets valides pour la prochaine tentative.

### Prévention des chevauchements

- Un propriétaire unique par fichier pendant chaque lot.
- Les changements F02/F05 sont intégrés ensemble dans le packaging ; F03/F04/F10 ensemble dans l’updater ; F06/F07/F13
  ensemble dans la validation et les hooks.
- Les lots E, F et G modifient les contrats CI successivement, sous un intégrateur unique.
- Les guides et contrats partagés sont modifiés par cet intégrateur à partir des comportements effectivement stabilisés.
- Aucune régénération concurrente des inventaires ou empreintes.

## 3. Contrat précis du réemploi CI — F14

### Éligibilité

Le réemploi est limité à `asphyx0r/git-starter-kit`, avec le rôle `source`.

- **Producteur admis :** qualification complète réussie d’un `push` <!-- codespell:ignore admis -->
  sur la branche par défaut. <!-- codespell:ignore branche -->
- **Consommateurs admis :** `push` d’un tag SemVer et <!-- codespell:ignore admis -->
  `release.published`.
- **Identité :** SHA strictement identique ; une égalité d’arbre ou une PR avant squash ne suffit pas.
- **Validité maximale :** sept jours, avec rétention Actions de sept jours.
- Examiner le producteur admissible le plus récent avant de considérer son résultat. Ne jamais contourner son échec en
  recherchant un ancien succès.
- Comparer workflow et validateur de confiance, politique, verrous,
  registre, versions effectivement exécutées et images <!-- codespell:ignore registre -->
  des deux OS.
- Absence, expiration, ambiguïté, erreur d’API ou divergence avant décision : qualification complète.

PR, exécutions manuelles, branches de préparation et consommateurs applicatifs conservent leurs qualifications
actuelles.

### Architecture

Un seul helper source, `C:\codex\git-starter-kit\tools\quality\qualification.py`, expose trois commandes :

- `resolve` : sélectionner un candidat et capturer son identité <!-- codespell:ignore candidat -->
  immuable ;
- `verify` : vérifier le paquet et les deux environnements, puis <!-- codespell:ignore environnements -->
  produire une décision unique `reuse` ou `full`, avec sa
  raison ; <!-- codespell:ignore raison -->
- `seal` : préparer le paquet après qualification complète d’un producteur autorisé.

Ce helper utilise les outils et bibliothèques existants. Il entre dans Mypy, les tests, la couverture et l’inventaire
documentaire. Il reste exclu des packages consommateurs ; les <!-- codespell:ignore reste -->
workflows exportés doivent fonctionner sans lui.

Le graphe comporte sept jobs :

**activation → deux préflights OS → décision commune → deux qualifications lourdes conditionnelles → agrégateur.**

L’agrégateur accepte exclusivement :

1. le paquet Linux/Windows antérieur intégralement vérifié ; ou
2. les deux qualifications complètes courantes.

Il ne mélange jamais un OS ancien avec un OS courant. Les identités originales du producteur restent intactes ; un
consommateur ne renouvelle ni leur date ni leur admissibilité.

### Ce qui reste frais <!-- codespell:ignore reste -->

Chaque événement conserve ses propres preuves et refait :

- contrôles de référence, SHA, plages de commits, messages et manifestes de tag ;
- audits de vulnérabilités npm/Python et scan de secrets ;
- validations statiques, contrats, versions et configurations ;
- smoke tests et résolutions dépendant du réseau ou de `latest` ;
- checks applicatifs des consommateurs sur les deux OS.

Seuls les résultats reproductibles des suites Python, de leur couverture et des suites de comportement shell peuvent
être réutilisés.

Le paquet conserve les comptes de tests, rapports, empreintes,
environnements et identités d’origine. Les seuils Linux <!-- codespell:ignore environnements -->
et combinés sont réévalués ; un simple statut vert n’est pas suffisant.

L’ordre local reste exactement : <!-- codespell:ignore reste -->

**statiques → couverture Python → comportement shell → smoke → Commitlint.**

Aucun drapeau permettant de supprimer les tests de `all`, `full` ou `static` n’est introduit.

## 4. Stratégie de non-régression

### Référence et tests ciblés

Avant modification, établir une référence complète avec les outils verrouillés sur Linux et Windows. Les 608 tests
observés dans l’audit servent de repère, pas de résultat futur <!-- codespell:ignore servent -->
présumé.

Pour chaque lot :

- Reproduire les défauts moyens par des tests qui échouent avant correction.
- Vérifier le cas corrigé et les comportements voisins explicitement préservés.
- Exécuter les suites affectées et les linters pertinents.
- Examiner le diff pour vérifier que chaque changement appartient au lot.
- Conserver séparément résultats initiaux, corrections, reprises et qualification complète.

Les tests CI utilisent les scripts réellement extraits des workflows, avec API simulées. Ils ne publient ni ne
suppriment de véritables assets.

### Tests spécifiques au réemploi

Refuser notamment :

- SHA différent, même avec arbre identique ;
- producteur PR, manuel, incomplet, échoué ou plus récent défaillant ;
- workflow, politique, verrou, version ou image divergente ;
- OS manquant, données altérées, preuve expirée ;
- mélange de runs ou de tentatives ;
- disparition de la preuve après sélection.

Prouver également que le réemploi exécute tous les contrôles frais et que le repli impose les deux qualifications
complètes.

### Qualification finale

Sur le contenu final figé :

- Audits complets Linux et Windows, suites Bash et contrôles <!-- codespell:ignore complets -->
  PowerShell.
- Ruff, Mypy, Markdownlint, Yamllint, Actionlint, ShellCheck et shfmt verrouillés.
- Maintien des seuils et du périmètre de couverture ; aucune exclusion ou permission assouplie.
- Packaging, initialisation, upgrade et restauration dans des <!-- codespell:ignore restauration -->
  fixtures possédées par la tâche.
- Validation des packages consommateurs et du README embarqué dans le toolkit.
- Tests adversariaux des contrats avant recalcul de leurs empreintes.
- Mesure des chemins CI sans preuve, avec preuve valide et avec <!-- codespell:ignore mesure,valide -->
  preuve invalidée.

Pour F14, mesurer le gain sur une séquence complète de release ainsi que le surcoût du repli. Ne pas annoncer de gain
avant ces mesures. <!-- codespell:ignore mesures -->

## 5. Documentation, intégration et critères de clôture

La documentation est livrée avec le comportement correspondant : <!-- codespell:ignore correspondant -->

- Guides source et templates consommateurs uniquement lorsqu’ils décrivent ce comportement.
- Aide CLI, sortie JSON et README du toolkit synchronisés.
- Une référence canonique pour le protocole de qualification ; les autres guides y renvoient.
- Documents historiques conservés comme preuves datées.
- Inventaires, listes d’exclusion et empreintes générées actualisés après intégration, sans présenter le contenu
  candidat comme celui de la release publiée. <!-- codespell:ignore candidat -->

Ordre d’intégration : **A → B/C/D → E/F → G → qualification finale**. B, C et D peuvent être étudiés indépendamment ;
les écritures dans les surfaces partagées restent séquentielles.

Chaque constat est fermé seulement lorsque ses preuves sont
disponibles. F12 exige un environnement réellement <!-- codespell:ignore environnement -->
sélectionné ; F10, F11 et F16 exigent des contrats documentaires cohérents ; F14 exige les scénarios de réemploi, de
refus, de repli et les mesures de coût. <!-- codespell:ignore mesures -->

La validation hébergée fera l’objet d’une étape explicitement autorisée. Ses résultats seront liés au SHA final et aux
tentatives exactes. Push, intégration et release restent des opérations distinctes.

Tous les temporaires créés lors de l’exécution seront inventoriés, nettoyés et leur absence vérifiée, sans supprimer les
environnements préexistants. <!-- codespell:ignore environnements -->

Ce plan a été préparé en lecture seule, selon les consignes du dépôt et les règles de documentation applicables. Aucun
fichier n’a été créé ou modifié ; aucun test produisant des fixtures n’a été exécuté pendant sa préparation.

## Amendement accepté pour F14 — 2026-10-16 <!-- codespell:ignore amendement -->

L'utilisateur a accepté de remplacer le critère de mesure <!-- codespell:ignore mesure -->
d'une véritable séquence de release par une validation expérimentale, sans merge, tag ni release.
Le protocole canonique est décrit dans
[Release package — Accepted F14 experiment](../../release-package.md#accepted-f14-experiment).

Une qualification complète réelle sert de chauffe et de paire producteur. Trois répétitions isolées sur chaque OS
mesurent les chemins sans preuve, avec preuve valide <!-- codespell:ignore valide -->
et avec preuve invalidée ; la perte après décision doit être refusée.
Les événements admissibles sont simulés uniquement dans une API injectée au banc. Les règles de production,
les données brutes, les identités originales et les quatre seuils de 85 % restent inchangés.

La clôture alternative exige les résultats complets, <!-- codespell:ignore complets -->
les environnements appariés, les empreintes et les coûts <!-- codespell:ignore environnements -->
par composant. La comparaison de deux consommateurs <!-- codespell:ignore composant,comparaison -->
est un coût assemblé, sans prétendre mesurer une séquence de release réelle.
Le rapport doit distinguer le commit du banc mesuré du commit documentaire final.
