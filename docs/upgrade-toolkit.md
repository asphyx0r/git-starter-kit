# Fonctionnement de `git-starter-kit-vX.Y.Z-upgrade-toolkit.zip`

Ce ZIP n'est pas un patch directement applicable. C'est une boîte à outils permettant de construire un patch cumulatif
adapté à la version d'origine du dépôt.

Il contient exactement :

```text
README.md
starter-kit-upgrade.py
process_runner.py
starter_kit_upgrade/__init__.py
starter_kit_upgrade/application.py
starter_kit_upgrade/archive.py
starter_kit_upgrade/cli.py
starter_kit_upgrade/common.py
starter_kit_upgrade/planning.py
packages/git-starter-kit-vX.Y.Z-with-agent-rules.zip
```

## Utilisation

Supposons que le dépôt ait été initialisé avec `v2.0.3` et doive passer à `v2.2.1`.

1. Télécharger et extraire :

   ```text
   git-starter-kit-v2.2.1-upgrade-toolkit.zip
   ```

2. Fournir le package exact utilisé lors de l'initialisation :

   ```text
   git-starter-kit-v2.0.3-with-agent-rules.zip
   ```

3. Construire le patch cumulatif :

   ```powershell
   python starter-kit-upgrade.py build `
     --base-package git-starter-kit-v2.0.3-with-agent-rules.zip `
     --new-package packages/git-starter-kit-v2.2.1-with-agent-rules.zip `
     --output git-starter-kit-v2.0.3-to-v2.2.1-upgrade.zip
   ```

4. Examiner le plan sans modifier le dépôt :

   ```powershell
   python starter-kit-upgrade.py plan `
     --upgrade-package git-starter-kit-v2.0.3-to-v2.2.1-upgrade.zip `
     --target C:\codex\qmd-manager
   ```

5. Appliquer seulement si le plan ne contient aucun état `conflict` :

   ```powershell
   python starter-kit-upgrade.py apply `
     --upgrade-package git-starter-kit-v2.0.3-to-v2.2.1-upgrade.zip `
     --target C:\codex\qmd-manager `
     --backup-directory C:\upgrade-backups
   ```

## Journal d'exécution

Chaque commande `build`, `toolkit`, `plan` ou `apply` exécutée hors mode
`--dry-run` crée un journal UTF-8 dans le sous-répertoire `logs` du répertoire
courant :

```text
starter-kit-upgrade-vX.Y.Z-YYYYMMDD-HHMMSS.log
```

La release cible validée détermine `vX.Y.Z`. Tous les timestamps affichés dans
le contenu du journal utilisent `YYYY-MM-DD HH:MM:SS` ; seul le nom de fichier
emploie le format compact imposé. Le chemin absolu du journal est annoncé sur
la sortie d'erreur afin de préserver la sortie standard JSON de `plan`.

Le journal détaille les phases, les provenances et empreintes d'archives, ainsi
que l'action, la stratégie et les empreintes pertinentes de chaque fichier lu,
préservé, délégué, sauvegardé ou écrit. Sa synthèse distingue l'état de
l'opération, la conformité opérationnelle aux stratégies du starter kit et
l'alignement exact avec tous les fichiers de la release cible. Le journal
signale explicitement les revues `initialize-only` et la synchronisation
déléguée des règles, même lorsque l'application automatisée a réussi.

Un verdict final `NON_COMPLIANT` produit un code de sortie non nul et l'état
`FAILED`. Les états `COMPLIANT_WITH_FOLLOW_UP` et `NOT_ALIGNED` restent compatibles
avec une application réussie lorsque les stratégies sont respectées. Si une
modification concurrente cause l'échec du contrôle final, elle reste préservée.

Le mode `--dry-run` ne réalise aucune écriture et ne crée aucun journal.
Il en va de même pour l'aide, la version, les erreurs d'arguments et les erreurs
survenant avant que la release cible puisse être résolue. Après cette
résolution, les échecs et leur trace complète sont consignés. Si le journal ne
peut pas être créé, aucune archive ni aucun fichier cible n'est écrit.

## Traitement des fichiers

Chaque fichier est associé à une stratégie :

- `replace` : remplacé uniquement si sa version locale correspond à la base connue.
- `merge` : fusion à trois sources entre ancienne version, version locale et nouvelle version.
- `initialize-only` : conservé dans le dépôt cible ; le plan demande seulement une revue manuelle.
- `agent-rules` : les sept fichiers de règles restent confiés au workflow autonome ;
  dans `_agent-rules-source.json`, seules les sections `repository` et `starterKit`
  sont actualisées, sans modifier les données locales liées aux règles.
- `starter-kit-state` : conserve la release `source`, puis met à jour `current` et l'inventaire du core.
- Fichier supprimé du starter : conservé, jamais supprimé automatiquement.
- Fichier non suivi sans rapport : conservé.

Les documentations et audits propres au dépôt, notamment `docs/SKILLS.md`, `docs/repository-files.md`,
`tools/README.md` et `tools/repository-audit.sh`, ne sont donc pas écrasés aveuglément.

Après application, `starter-kit-manifest.json` conserve la release ayant servi
de source initiale et identifie séparément la dernière release cumulative
appliquée. Le manifeste d'adoption ancre aussi cette source immuable ; une
altération de la source ou des données courantes bloque le patch.

## Sécurité

L'application exige :

- un dépôt Git sans modification suivie ;
- une provenance compatible avec le package de base ;
- aucun état `conflict` ;
- un répertoire de sauvegarde extérieur au dépôt.

Les archives sont limitées à 10 000 membres, répertoires inclus, et à 256 Mio
décompressés. Leurs chemins doivent être relatifs et uniques sans distinction
de casse. Les chemins Windows dangereux, noms de périphériques, flux alternatifs,
composants `.git`, liens et types ZIP spéciaux sont refusés. Les fichiers cibles
doivent rester dans le dépôt et ne traverser aucun lien ni point de réanalyse
Windows, notamment une jonction.

Les manifestes v1, v2 et v3 sont validés avant le plan et les sauvegardes : types,
stratégies, modes, provenance et empreintes des contenus disponibles. Les anciens
formats restent acceptés sans leur imposer les champs apparus ensuite.

En cas d'erreur ou d'interruption pendant l'écriture, l'outil tente de restaurer
tous les fichiers modifiés et l'adoption, avec leur contenu et leur mode initial.
Il conserve le ZIP de rollback. Si une restauration échoue, les autres sont
encore tentées ; chaque chemin en échec est signalé et l'interruption d'origine
est propagée. Une restauration complète n'est donc pas garantie si le système
refuse lui-même les écritures de restauration.

Les requêtes Git courtes sont limitées à 30 secondes et les fusions à 300 secondes.
Le délai couvre aussi les flux capturés et l'arrêt des processus descendants
ordinaires. Un dépassement devient une erreur explicite ; les fichiers
temporaires de fusion sont nettoyés.
Ce délai démarre après la création synchrone et la mise sous contrôle du
processus ; ces API ne permettent pas d'annuler la création native elle-même.

L'outil ne réalise aucun commit, tag, push ou accès réseau.

Avec le workflow actuel, ce toolkit est produit pour chaque release réussie de `git-starter-kit`. Les dépôts dérivés
ne reçoivent ni le producteur du package enrichi ni le toolkit, et ne publient aucun de ces deux assets.
