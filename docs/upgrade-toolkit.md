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
   python starter-kit-upgrade.py --dry-run plan `
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
modification concurrente cause l'échec du contrôle final, elle est préservée.

Le mode `--dry-run` n'applique aucune modification aux fichiers de la cible et
ne crée ni archive de sortie, ni sauvegarde, ni journal. Les vérifications de
fusion peuvent créer puis nettoyer des fichiers temporaires : le répertoire
temporaire du système doit être accessible en écriture. Ce mode ne désactive
pas les éventuelles actualisations des métadonnées locales par Git.
L'aide, la version, les erreurs d'arguments et les erreurs survenant avant
résolution de la release cible ne créent pas non plus de journal. Après cette
résolution, les échecs et leur trace complète sont consignés. Si le journal ne
peut pas être créé, aucune archive ni aucun fichier cible n'est écrit.

Une panne du journal ne masque jamais l'erreur ou l'interruption initiale.
La finalisation tente la synthèse, le vidage, la synchronisation et la fermeture,
en signalant aussi les erreurs secondaires sur stderr. Si elle échoue seule
après une application réussie, le code de sortie est non nul, mais les changements
appliqués sont conservés ; aucun rollback n'est annoncé. Examiner le résultat et
les diagnostics avant de relancer. La sortie JSON est maintenue sur stdout.

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

Un fichier local déclaré comme texte mais non décodable en UTF-8 est conservé.
Son entrée de plan porte `localCanonicalSha256: null` et un champ additionnel
`localRawSha256`, utilisé pour détecter les modifications concurrentes. Les
plans de textes valides gardent leur forme JSON. Les stratégies `replace` et
`merge` signalent `conflict-modified`, sans fusion ; `initialize-only` et les
règles déléguées conservent leurs politiques. Toute provenance ou tout état géré
JSON malformé est traité comme un état conflictuel. Les formats et contrôles d'archives et
d'adoption ne sont pas assouplis.

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
segments `.git`, liens et types ZIP spéciaux sont refusés. Les fichiers cibles
doivent rester dans le dépôt et ne traverser aucun lien ni point de réanalyse
Windows, notamment les liens de type `junction`.

Les manifestes v1, v2 et v3 sont validés avant le plan et les sauvegardes : types,
stratégies, modes, provenance et empreintes des contenus disponibles. Les anciens
formats restent acceptés sans leur imposer les champs apparus ensuite.

En cas d'erreur ou d'interruption pendant l'écriture, l'outil restaure le contenu,
le mode et l'adoption uniquement si leur état correspond encore à l'écriture
attendue de l'upgrade. Un fichier déjà dans son état initial est laissé inchangé.
Les modifications concurrentes observées sont préservées et signalées comme un
rollback incomplet. Le ZIP de rollback est conservé. Si une remise en état
échoue, les autres sont encore tentées ; chaque chemin en échec est signalé et
l'interruption d'origine est propagée, même si le journal ou la sortie
diagnostique échoue. Le contrôle et la remise en état sont deux opérations
distinctes : ils ne constituent pas une transaction atomique face aux écritures
provenant d'autres programmes.

Les requêtes Git courtes sont limitées à 30 secondes et les fusions à 300 secondes.
Le délai couvre aussi les flux capturés et l'arrêt des programmes descendants
ordinaires. Un dépassement produit un diagnostic d'erreur ; les fichiers
temporaires de fusion sont nettoyés.
Ce délai démarre après la création synchrone et la mise sous contrôle du
programme ; ces API ne permettent pas d'annuler la création native elle-même.

L'outil ne réalise aucun commit, tag, push ou accès réseau.

Avec le workflow actuel, ce toolkit est produit pour chaque release réussie de `git-starter-kit`. Les dépôts dérivés
ne reçoivent ni le producteur du package enrichi ni le toolkit, et ne publient aucun de ces deux assets.
