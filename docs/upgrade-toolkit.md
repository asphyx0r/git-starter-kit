# Fonctionnement de `git-starter-kit-vX.Y.Z-upgrade-toolkit.zip`

Ce ZIP n'est pas un patch directement applicable. C'est une boîte à outils permettant de construire un patch cumulatif
adapté à la version d'origine du dépôt.

Il contient exactement :

```text
README.md
starter-kit-upgrade.py
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

## Traitement des fichiers

Chaque fichier est associé à une stratégie :

- `replace` : remplacé uniquement si sa version locale correspond à la base connue.
- `merge` : fusion à trois sources entre ancienne version, version locale et nouvelle version.
- `initialize-only` : conservé dans le dépôt cible ; le plan demande seulement une revue manuelle.
- `agent-rules` : jamais écrit par le patch ; confié au workflow autonome des règles.
- Fichier supprimé du starter : conservé, jamais supprimé automatiquement.
- Fichier non suivi sans rapport : conservé.

Les documentations et audits propres au dépôt, notamment `docs/SKILLS.md`, `docs/repository-files.md`,
`tools/README.md` et `tools/repository-audit.sh`, ne sont donc pas écrasés aveuglément.

## Sécurité

L'application exige :

- un dépôt Git sans modification suivie ;
- une provenance compatible avec le package de base ;
- aucun état `conflict` ;
- un répertoire de sauvegarde extérieur au dépôt.

Le fonctionnement est tout-ou-rien. En cas d'erreur d'écriture, les fichiers déjà modifiés sont immédiatement
restaurés. Un ZIP de rollback contient les anciennes versions.

L'outil ne réalise aucun commit, tag, push ou accès réseau.

Avec le workflow actuel, ce toolkit est produit pour chaque release réussie de `git-starter-kit`. Les dépôts dérivés
publient seulement leur package enrichi, pas un toolkit.
