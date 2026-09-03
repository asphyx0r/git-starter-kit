# Tools

<!-- markdownlint-disable MD024 -->

This directory contains small repository management tools for the Git starter
kit. Each tool is documented as an operational reference: what it does, how to
run it, which options it accepts, how it exits, and what practices keep usage
safe.

## backup-target-directory.py

### Features

- Copies an entire source directory tree into a temporary staging directory.
- Includes Git metadata, hidden files, and tracked, untracked, or ignored files
  that are present during the copy.
- Creates a compressed ZIP archive in a separate existing target directory.
- Rejects symbolic links in the source tree.
- Names archives with the source directory, timestamp, Git `HEAD`, and an exact
  matching SemVer tag.
- Supports a side-effect-free dry run and an optional staging parent directory.

### Synopsis

```text
usage: python tools/backup-target-directory.py [options]

options:
  -h, --help                       show help and exit
  --version                        show version and exit
  --dry-run                        simulate execution without modifying data
  -v, --verbose                    enable DEBUG logs
  -d, --source-directory BASEDIR   existing source directory tree to back up
  -t, --target-directory TARGETDIR existing directory for the ZIP archive
  -b, --buffer-directory BUFFERDIR existing staging parent directory
```

### Description

`backup-target-directory.py` creates a staged ZIP backup of an existing
directory tree. The target and staging directories must remain outside the
source so the generated data cannot enter the backup. The script copies the
source to temporary staging before creating a same-directory temporary ZIP and
publishing the final archive.

When the source belongs to a readable Git repository, the archive name records
the 12-character abbreviated `HEAD`. It includes a SemVer tag only when that
tag points exactly to the captured commit. Every final archive uses this
format:

```text
<SOURCE>-<YYYYMMDD>-<HHMMSS>-<HEAD>-<SEMVER-TAG>.zip
```

For example:

```text
git-starter-kit-20260730-165813-0d3ae03a4a86-v2.0.3.zip
```

When no commit can be read, `<HEAD>` is `000000000000`. When no matching
SemVer tag can be read, `<SEMVER-TAG>` is `v0.0.0`. These placeholders keep
the filename structure stable.

After staging, the script resolves the source Git identity again. It stops
before ZIP creation if `HEAD` or the selected tag changed during the copy.

### Usage/Examples

Preview a backup of the current repository into an existing sibling
directory:

```bash
python tools/backup-target-directory.py \
  --dry-run \
  --source-directory . \
  --target-directory ../backups
```

Create the archive:

```bash
python tools/backup-target-directory.py \
  --source-directory . \
  --target-directory ../backups
```

Use an existing staging parent on another volume:

```bash
python tools/backup-target-directory.py \
  --source-directory . \
  --target-directory ../backups \
  --buffer-directory /path/to/staging
```

### Options

- `-h`, `--help`: prints the version and usage information, then exits.
- `--version`: prints script version `0.1.0`, then exits.
- `--dry-run`: validates the source, target, staging location, symbolic-link
  policy, Git identity, and final name without creating staging data or a ZIP.
- `-v`, `--verbose`: prints DEBUG logs in addition to normal status messages.
- `-d PATH`, `--source-directory PATH`: existing directory tree to back up.
  This option is required.
- `-t PATH`, `--target-directory PATH`: existing directory where the ZIP is
  created. This option is required and must not be inside the source.
- `-b PATH`, `--buffer-directory PATH`: optional existing staging parent. An
  unusable value produces a warning and falls back to the user temporary
  directory.

### Exit Status

- `0`: help or version was shown, the dry run completed, or the archive was
  created successfully.
- `1`: path or filesystem validation failed, a symbolic link was found, the
  Git identity changed during staging, or staging/archive creation failed.
- `2`: command-line argument parsing failed.

The script also refuses to run with effective user ID `0` on Linux.

### Appendix

This is a staged filesystem copy, not a transactional repository snapshot.
The post-copy check detects changes to `HEAD` or the selected tag, but not
concurrent edits to working-tree files, the index, other refs, or reflogs. Stop
repository writers while the backup runs when a restorable point-in-time copy
is required.

The archive includes `.git` when it is contained in the source. Linked
worktrees and submodules may instead use a `.git` file that refers to metadata
outside the source; such an archive is not self-contained.

ZIP preserves file bytes and modification times at ZIP precision, but this
tool does not preserve NTFS ACLs, alternate data streams, creation/access
times, or a cryptographic manifest. The `v0.0.0` placeholder is also
indistinguishable in the filename from a real tag with that exact name.

## release-artifacts.py

### Features

- Generates root `VERSION`, `SHA256SUMS`, and `manifest.json` files for one
  exact SemVer release.
- Reads Git blobs from `HEAD`, the index, or a selected tree instead of hashing
  untracked, ignored, or checkout-normalized files.
- Generates the manifest from `templates/release/manifest.template.json` and
  validates it against `templates/release/manifest.schema.json`.
- Requires release-specific business metadata from an external JSON file and
  never derives unknown values from repository content.
- Supports side-effect-free preparation and exact index or tag validation.

### Synopsis

```text
usage: python tools/release-artifacts.py [options] COMMAND

options:
  -h, --help    show help and exit
  --version     show version and exit
  --dry-run     validate and print the execution plan without writing
  -v, --verbose show additional diagnostics
  --force       write without interactive confirmation

commands:
  prepare prepare release artifacts
  check   validate release artifacts
```

Install the pinned validator first:

```bash
python -m pip install \
  --no-input \
  --require-hashes \
  --requirement tools/release-artifacts-requirements.txt
```

### Metadata Contract

`prepare` requires a UTF-8 JSON object outside the repository with exactly
these fields:

```json
{
  "program_id": "example-app",
  "name": "Example App",
  "channel": "stable",
  "critical_update": false,
  "release_notes": ["Describe an actual release change."],
  "update": {
    "min_source_version": "1.0.0",
    "strategy": "patch",
    "preserve_paths": [],
    "remove_obsolete_files": false,
    "backup_required": false,
    "restart_required": false,
    "rollback_supported": false,
    "migrations": []
  },
  "artifact": {
    "id": "source-tree",
    "target": {
      "os": "any",
      "arch": "any",
      "min_os_version": "not-applicable"
    }
  },
  "metadata": {
    "author": "Example Maintainers",
    "license": "MIT",
    "support_url": "https://example.com/support"
  }
}
```

This object illustrates the required types only. None of its values is a
default. The caller must provide every exact value. The canonical release
workflow resolves provable values from explicit current input, authoritative
project sources, exact release facts, or a non-conflicting previous manifest.
It asks the user only for unresolved or contradictory values and requires
explicit validation. Do not copy illustrative values into a real release.

### Usage/Examples

Preview generation with one recorded UTC timestamp:

```bash
python tools/release-artifacts.py --dry-run prepare \
  --release-ref v1.2.3 \
  --release-date 2026-08-18T12:00:00Z \
  --metadata-file /external/path/release-metadata.json
```

Generate the three files after the preview succeeds:

```bash
python tools/release-artifacts.py --force prepare \
  --release-ref v1.2.3 \
  --release-date 2026-08-18T12:00:00Z \
  --metadata-file /external/path/release-metadata.json
```

Validate the staged files before committing them:

```bash
python tools/release-artifacts.py check \
  --expected-ref v1.2.3 \
  --index
```

Validate the immutable tag tree:

```bash
python tools/release-artifacts.py check \
  --expected-ref v1.2.3 \
  --treeish v1.2.3
```

### Artifact Scope

The generated inventory contains every supported Git blob in the candidate
release tree, plus the generated `VERSION`. Gitlinks and untracked, ignored, or
absent paths are excluded. `SHA256SUMS` and `manifest.json` are also excluded
from the checksum inventory because either digest would create a
self-reference. The SHA-256 recorded for the `git-tree` artifact is the digest
of the exact `SHA256SUMS` bytes.

### Options

- `--release-ref TAG`: exact SemVer release tag, including the leading `v`.
- `--release-date TIMESTAMP`: exact UTC release timestamp in
  `YYYY-MM-DDTHH:MM:SSZ` format.
- `--metadata-file PATH`: required release-specific JSON file outside the Git
  root.
- `--expected-ref TAG`: exact tag required by `check`; otherwise the manifest
  version determines the expected tag.
- `--index`: validate staged Git content.
- `--treeish REF`: validate one committed tree or tag. It is mutually exclusive
  with `--index`.
- `--repository-root PATH`: exact Git root. Defaults to the current directory.

### Exit Status

- `0`: help or version was shown, the dry run succeeded, or all requested
  artifacts were prepared or validated.
- `1`: metadata, SemVer, Git content, checksum, template, schema, confirmation,
  or write validation failed.
- `2`: command-line argument parsing failed.

## starter-kit-manifest.py

This is a `git-starter-kit` source-repository tool. It prepares and validates
the tracked core release manifest. The tool is excluded from packages, while
the generated `starter-kit-manifest.json` is distributed to derived
repositories.

### Features

- Records separate immutable `source` and updatable `current` releases.
- Inventories core paths with raw and canonical SHA-256 digests, Git modes,
  content kinds, and upgrade strategies.
- Reads committed or staged Git blobs so the inventory is independent of
  checkout line endings.
- Preserves an existing generation timestamp when the selected ref and core
  inventory are unchanged.
- Allows read-only validation in forks but permits preparation only with the
  exact canonical `asphyx0r/git-starter-kit` `origin`.
- Uses only the Python standard library.

### Synopsis

```text
usage: python tools/starter-kit-manifest.py [options] COMMAND

options:
  -h, --help    show help and exit
  --version     show version and exit
  --dry-run     validate and print the execution plan without writing
  -v, --verbose show additional diagnostics

commands:
  prepare prepare the tracked manifest
  check   validate the tracked manifest
```

### Usage/Examples

Preview preparation for an exact release tag:

```bash
python tools/starter-kit-manifest.py --dry-run prepare \
  --release-ref v2.4.0
```

Prepare and validate the manifest after all other release content is
committed:

```bash
python tools/starter-kit-manifest.py prepare --release-ref v2.4.0
python tools/starter-kit-manifest.py check \
  --expected-ref v2.4.0 \
  --treeish HEAD
```

By default, `check` validates the core against the tag recorded in `current`
when that tag exists locally. This keeps the last published baseline valid on
a development branch containing later unreleased changes.

### Options

- `--release-ref TAG`: exact SemVer release tag for `prepare`, including the
  leading `v`.
- `--expected-ref TAG`: optional exact `current` ref required by `check`.
- `--repository-root PATH`: Git repository root. Defaults to the current
  directory.
- `--treeish REF`: Git tree whose committed blobs define the core. `prepare`
  otherwise reads staged index blobs; `check` otherwise resolves the recorded
  release tag or uses the index when that tag does not exist.

### Exit Status

- `0`: the manifest was prepared or validated successfully.
- Non-zero: repository identity, schema, release metadata, Git inventory, or
  digest validation failed.

## build-release-package.ps1

This is a `git-starter-kit` source-repository tool. It is intentionally absent
from packages distributed to derived repositories.

### Features

- Builds an enriched repository ZIP package.
- Copies manifest-declared core files into a temporary staging directory for
  SemVer releases and tracked files for local smoke packages.
- Validates tracked coding-agent rule files against their source provenance.
- Writes `_agent-rules-source.json` with repository, starter-kit, resolved
  rule provenance, and any preserved customization records.
- Writes schema 3 `_starter-kit-files.json` with managed-file hashes, modes,
  upgrade strategies, and `starter-kit-state` handling.
- Verifies required files before and after ZIP creation.
- Builds and validates a sibling temporary ZIP before atomically publishing it;
  a failed build, validation, or replacement preserves an existing destination.
- Emits GitHub Actions outputs when `GITHUB_OUTPUT` is set.
- Rejects every repository slug and `origin` except the canonical
  `asphyx0r/git-starter-kit` repository.
- Excludes source-only workflow, builder, upgrade, test, and operator
  documentation paths, plus the canonical repository's generated `VERSION`,
  `SHA256SUMS`, and `manifest.json`, from the distributed package and its
  manifest.

### Synopsis

```text
usage: powershell -NoProfile -File tools\build-release-package.ps1 [options]

options:
  -RepositoryRoot PATH        repository root to package
  -OutputDirectory PATH       directory where the ZIP is written
  -PackageName NAME           ZIP file name, with .zip appended if needed
  -RepositoryRef REF          packaged repository ref
  -RepositorySlug OWNER/NAME  packaged GitHub repository
  -StarterKitRepository NAME  upstream starter-kit owner/name
  -StarterKitRef REF          upstream starter-kit ref
  -StarterKitCommit SHA       upstream starter-kit commit
  -AgentRulesRepository NAME  owner/name repository for agent rules
  -AgentRulesRef REF          latest or SemVer agent-rules tag
```

### Description

`build-release-package.ps1` creates the release asset used by the
`Release package` GitHub Actions workflow. It packages files reported by
`starter-kit-manifest.json` for SemVer releases, plus the required coding-agent
rule files already tracked by the repository. Non-SemVer local smoke packages
continue to use `git ls-files` minus the explicit starter-only exclusion list.
It resolves an `agent-coding-rules` release only to assert
that provenance and canonical rule hashes are current. The generated ZIP
includes the normal repository content, the required rule files,
`starter-kit-manifest.json`, `_agent-rules-source.json`, and the per-file
`_starter-kit-files.json` upgrade manifest. For a SemVer package, the tracked
core manifest must identify the exact packaged ref and match `HEAD`; the tag
must resolve to `HEAD`, and every packaged path must match its filtered `HEAD`
blob. The builder accepts only the exact canonical starter repository slug and
HTTPS `origin`; derived repositories cannot use it to create their own release
package.

The script resolves `-AgentRulesRef latest` through the GitHub releases API.
An explicit `-AgentRulesRef` must be a SemVer tag prefixed with `v`.
Branch names and other refs are rejected to keep package inputs reproducible.

### Usage/Examples

Create a local test package in the ignored `.tmp/` directory:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
  -RepositoryRef local-test `
  -RepositorySlug asphyx0r/git-starter-kit `
  -OutputDirectory .tmp\release-package-test `
  -PackageName test-release-package.zip
```

Create a package with a specific agent-rules release:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
  -RepositoryRef v1.5.0 `
  -RepositorySlug asphyx0r/git-starter-kit `
  -AgentRulesRef v1.36.1 `
  -OutputDirectory dist
```

Inspect the generated archive:

```powershell
tar -tf .tmp\release-package-test\test-release-package.zip
tar -xOf .tmp\release-package-test\test-release-package.zip `
  _agent-rules-source.json
```

### Options

- `-RepositoryRoot PATH`: repository root to package. Defaults to the current
  working directory.
- `-OutputDirectory PATH`: output directory for the generated ZIP. Defaults to
  `dist` under the current working directory. The directory is created when
  needed.
- `-PackageName NAME`: output file name. When omitted, the script derives
  `{RepositoryName}-{RepositoryRef}-with-agent-rules.zip`. If the provided
  name does not end with `.zip`, the extension is appended.
- `-RepositoryRef REF`: packaged repository ref recorded in the manifest and
  used in the default package name. `-StarterRef` remains an alias for
  compatibility. Defaults to `GITHUB_REF_NAME`; if that is empty, the script
  uses the short current commit SHA.
- `-RepositorySlug OWNER/NAME`: packaged GitHub repository. It must resolve
  exactly to `asphyx0r/git-starter-kit`. In Actions it defaults to
  `GITHUB_REPOSITORY`; local invocations must pass the canonical slug. The
  repository root must also use the canonical HTTPS `origin`.
- `-StarterKitRepository OWNER/NAME`: upstream starter-kit repository recorded
  in the provenance. Defaults to `asphyx0r/git-starter-kit`.
- `-StarterKitRef REF`: upstream starter-kit ref. Defaults to the packaged
  repository ref when the packaged repository is the starter kit.
- `-StarterKitCommit SHA`: upstream starter-kit commit. Defaults to the
  packaged repository commit when the packaged repository is the starter kit.
- `-AgentRulesRepository NAME`: GitHub `owner/name` repository used as the
  agent-rules source. Defaults to `asphyx0r/agent-coding-rules`.
- `-AgentRulesRef REF`: agent-rules reference to package. Defaults to
  `latest`. Accepted values are `latest` or a SemVer tag prefixed with `v`.
- `GITHUB_TOKEN`: optional environment variable used as a bearer token for the
  public GitHub releases API when resolving `latest`; no token is required for
  the canonical public source.
- `GITHUB_OUTPUT`: optional environment variable used by GitHub Actions. When
  set, the script writes `package_path`, `package_name`, `agent_rules_ref`,
  and `agent_rules_commit`.

### Exit Status

- `0`: the package was created successfully.
- Non-zero: validation failed, Git failed, GitHub API resolution failed,
  required rule files were missing, archive verification failed, or another
  terminating PowerShell error occurred.

### Appendix

Use this script from a clean, committed repository when preparing release
assets. Local untracked files are intentionally excluded because package
content comes from `git ls-files`.

Use `latest` for normal release automation so packaging fails if tracked rules
lag behind the latest full `agent-coding-rules` release. Use an explicit SemVer
tag only when recreating a package from a known rules release.

Treat failures as release blockers. The script verifies the resolved
agent-rules tag, tracked rule hashes, preserved customization records, and the
generated archive so that a broken package is not uploaded silently.

## starter-kit-upgrade.py

This is a `git-starter-kit` source-repository tool. It is excluded from the
full package and supplied separately inside the upgrade toolkit so derived
repositories do not track the toolkit builder or applier.

### Features

- Builds cumulative upgrade ZIPs from exact base and new release packages.
- Verifies release provenance, managed-file hashes, and archive paths.
- Produces a per-file plan without modifying the target.
- Compares text through canonical UTF-8, LF, and final-newline hashes.
- Updates unchanged files and three-way merges explicitly merge-managed files.
- Delegates the seven root rule files to the target repository's autonomous rule
  synchronization workflow.
- Refreshes only the starter-owned `repository` and `starterKit` sections in
  `_agent-rules-source.json` while preserving agent-rule and target-owned data.
- Preserves `starter-kit-manifest.json.source` while replacing `current` and
  the core inventory from the new release.
- Preserves initialization-only, deleted, additional, unrelated untracked, and
  conflicting locally modified files.
- Requires no tracked worktree changes, an external rollback directory, and
  zero conflicts before application.
- Bundles the updater and a complete new package as a release toolkit.
- Writes a detailed, release-specific execution log for every non-dry-run
  command.

### Synopsis

```text
usage: python tools/starter-kit-upgrade.py [options] COMMAND

options:
  -h, --help    show help and exit
  --version     show version and exit
  --dry-run     validate and print the execution plan without writing
  -v, --verbose show additional diagnostics

commands:
  build   build a cumulative upgrade ZIP
  toolkit bundle the updater and a new full package
  plan    inspect a target without writing
  apply   apply a conflict-free upgrade
```

### Usage/Examples

Build an upgrade from the exact package used for initialization:

```bash
python tools/starter-kit-upgrade.py build \
  --base-package git-starter-kit-v2.0.3-with-agent-rules.zip \
  --new-package git-starter-kit-v2.1.0-with-agent-rules.zip \
  --output git-starter-kit-v2.0.3-to-v2.1.0-upgrade.zip
```

Inspect a target without modifying it:

```bash
python tools/starter-kit-upgrade.py plan \
  --upgrade-package git-starter-kit-v2.0.3-to-v2.1.0-upgrade.zip \
  --target ../example-repository
```

Apply a conflict-free plan while creating a rollback archive outside the
target:

```bash
python tools/starter-kit-upgrade.py apply \
  --upgrade-package git-starter-kit-v2.0.3-to-v2.1.0-upgrade.zip \
  --target ../example-repository \
  --backup-directory ../upgrade-backups
```

### Execution Log

Every non-dry-run `build`, `toolkit`, `plan`, and `apply` command creates a
UTF-8 log below `logs/` in the current directory. Its name uses the validated
target release and local start time:

```text
starter-kit-upgrade-vX.Y.Z-YYYYMMDD-HHMMSS.log
```

Every displayed log timestamp uses `YYYY-MM-DD HH:MM:SS`; the compact form is
used only in the required filename. The tool reports the absolute log path on
standard error so JSON and other normal standard output remain unchanged.

The log records command context, release provenance, archive hashes, processing
phases, and one action with relevant hashes for every inspected, preserved,
delegated, backed-up, or written file. Its final summary distinguishes the
operation status, strategy-aware operational compliance, and exact file
alignment with the target release. A successful operational result can still
require agent-rule synchronization or an explicit `initialize-only` review,
and exact alignment reports those intentional differences independently.

`--dry-run` remains side-effect free and creates no log. Help, version,
argument-parser exits, and failures that occur before a valid target release
can be resolved also create no log. A failure after release resolution is
recorded with its exception and traceback. If the log cannot be created, the
tool stops before writing an artifact or target file.

### Safety Model

The starter-kit commit recorded inside target `_agent-rules-source.json` must
match the base package. Agent-rule version changes and newline-only differences
do not invalidate this starter provenance. Older repositories can instead use
a reviewed `.starter-kit-adoption.json` that records the base archive hash,
starter-kit commit, and an ancestor commit containing the audited baseline.
Successful application writes the next adoption baseline, including hashes for
preserved merge-managed customizations.

The `starter-kit-state` strategy handles `starter-kit-manifest.json`
separately from ordinary file replacement. A legacy package without that file
receives `source` from the exact base-package provenance. Later upgrades
preserve `source`, replace `current` and `files`, and reject changes outside
the expected source-only difference. The adoption manifest anchors the
preserved source descriptor so a later local alteration is a conflict.

The distribution classifications are explicit. `.github/CODEOWNERS`, the
release-package workflow, packaging and upgrade sources, their
repository-specific tests, and package operator guides are source-only.
`.github/dependabot.yml` is merge-managed, `tools/quality/` is replaced as one
baseline, and the repository-audit dispatcher and modules are
initialization-only. The updater therefore preserves downstream inventories,
operator documentation, and repository-specific audit behavior.

When an initialization-only file changed upstream, the plan reports
`review-initialize-only` without blocking or writing the target. This makes
required local review visible while preserving repository ownership.

The tool performs no deletion, commit, tag, push, or network operation. An
upgrade is all-or-nothing: any conflict blocks application. If a write fails,
files already written in that attempt are restored immediately. The external
rollback ZIP records every replaced or merged file and the prior adoption
state for operator-controlled recovery.

## git-init.ps1

### Features

- Initializes an existing non-empty directory as a Git repository.
- Previews committable files before creating target Git metadata.
- Requires explicit confirmation before initialization and commit.
- Warns before committing risky credential, archive, cache, or runtime paths.
- Validates one temporary message file with Commitlint before committing it
  through the forced repository hooks.
- Creates the first Conventional Commit on `main`.
- Creates an annotated SemVer tag and optionally pushes to `origin`.

### Synopsis

```text
usage: powershell -NoProfile -File tools\git-init.ps1 [options]

options:
  -h, --help       show version and help
      --version    show version only
  -v, --verbose    show additional execution traces
  -p, --path PATH  target repository root, required
  -r, --remote URL optional origin remote URL
  -t, --tag TAG    SemVer Git tag, default: v1.0.0
```

### Description

`git-init.ps1` is the PowerShell initializer for creating the first Git history
in a target project directory. It requires the target directory to already
exist and contain files. If `.git` metadata already exists, it must be readable
and the repository must not already have commits.

The script asks for confirmation, previews files Git can commit, asks for a
second confirmation, warns on risky paths when needed, then creates the initial
commit from the exact temporary file accepted by `commitlint --edit` and the
forced `.githooks/commit-msg` hook. It compares the recorded message with that
file before renaming the branch to `main` and creating an annotated tag. It
pushes only when `--remote` is provided.

### Usage/Examples

Initialize a local target directory:

```powershell
powershell -NoProfile -File tools\git-init.ps1 `
  --path ..\example-app `
  --tag v1.0.0
```

Initialize and push to a remote repository:

```powershell
powershell -NoProfile -File tools\git-init.ps1 `
  --path ..\example-app `
  --tag v1.0.0 `
  --remote https://github.com/example/example-app.git
```

Show version and help:

```powershell
powershell -NoProfile -File tools\git-init.ps1 --help
powershell -NoProfile -File tools\git-init.ps1 --version
```

### Options

- `-h`, `--help`: prints the version and usage information, then exits.
- `--version`: prints the script version, then exits.
- `-v`, `--verbose`: prints Git commands before running them.
- `-p PATH`, `--path PATH`: target repository root. This option is required.
  The path must be an existing non-empty directory.
- `-r URL`, `--remote URL`: optional remote URL. When provided, the script adds
  it as `origin` and runs `git push -u origin main --tags`.
- `-t TAG`, `--tag TAG`: annotated Git tag to create. Defaults to `v1.0.0`.
  The tag must be a SemVer tag prefixed with `v`.

### Exit Status

- `0`: help or version was shown, the user cancelled safely, or initialization
  completed successfully.
- Non-zero: an argument was invalid, the target directory was invalid, Git
  metadata was unreadable, the repository already had commits, the tag already
  existed, no committable files were found, Commitlint or a Git hook failed,
  Git failed, or another terminating PowerShell error occurred.

### Troubleshooting

When `git-init.ps1` comes from a downloaded GitHub release ZIP, PowerShell may
block it before the script starts. The error can be localized, but it usually
includes `PSSecurityException`, `UnauthorizedAccess`, and text similar to:

```text
.\git-init.ps1 : File C:\Path\To\Project\tools\git-init.ps1 cannot be loaded.
The file C:\Path\To\Project\tools\git-init.ps1 is not digitally signed. You
cannot run this script on the current system.
FullyQualifiedErrorId : UnauthorizedAccess
```

PowerShell is enforcing the current execution policy or the downloaded-file
mark on the extracted script. Inspect the active policies, then use a per-user
`RemoteSigned` policy and unblock the trusted script file:

```powershell
Get-ExecutionPolicy -List
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
Unblock-File -Path .\tools\git-init.ps1
powershell -NoProfile -File .\tools\git-init.ps1 `
  --path ..\example-app `
  --tag v1.0.0
```

Use the actual path where you extracted or copied `git-init.ps1`; for example,
replace `.\tools\git-init.ps1` with `.\scripts\git-init.ps1` if the script was
copied to `scripts`. Unblock only files from a trusted release package. If an
organization manages execution policy through `MachinePolicy` or `UserPolicy`,
follow that policy instead of bypassing it.

### Appendix

Review the file preview before confirming the commit. If risky paths are
reported, inspect them carefully and cancel unless they are intentional.

The target must contain readable `.githooks/commit-msg` and
`commitlint.config.cjs` files. Install Commitlint and every tool required by
the target hooks before initialization. Any Commitlint or hook failure blocks
`HEAD`, the tag, and the optional push.

Use `--remote` only after checking that the target remote URL is correct. When
`--remote` is omitted, the initializer creates only local Git history.

Run from PowerShell when working primarily on Windows paths. Use
`git-init.sh` when a Bash environment is the better fit.

## git-init.sh

### Features

- Initializes an existing non-empty directory as a Git repository from Bash.
- Previews committable files before creating target Git metadata.
- Requires explicit confirmation before initialization and commit.
- Warns before committing risky credential, archive, cache, or runtime paths.
- Validates one temporary message file with Commitlint before committing it
  through the forced repository hooks.
- Creates the first Conventional Commit on `main`.
- Creates an annotated SemVer tag and optionally pushes to `origin`.

### Synopsis

```text
usage: bash tools/git-init.sh [options]

options:
  -h, --help       show version and help
      --version    show version only
  -v, --verbose    show additional execution traces
  -p, --path PATH  target repository root, required
  -r, --remote URL optional origin remote URL
  -t, --tag TAG    SemVer Git tag, default: v1.0.0
```

### Description

`git-init.sh` is the Bash initializer for creating the first Git history in a
target project directory. It requires Bash 4 or newer, an existing non-empty
target directory, and readable `.git` metadata if `.git` already exists. The
target repository must not already have commits.

The script asks for confirmation, previews files Git can commit, asks for a
second confirmation, warns on risky paths when needed, then creates the initial
commit from the exact temporary file accepted by `commitlint --edit` and the
forced `.githooks/commit-msg` hook. It compares the recorded message with that
file before renaming the branch to `main` and creating an annotated tag. It
pushes only when `--remote` is provided.

### Usage/Examples

Initialize a local target directory:

```bash
bash tools/git-init.sh --path ../example-app --tag v1.0.0
```

Initialize and push to a remote repository:

```bash
bash tools/git-init.sh \
  --path ../example-app \
  --tag v1.0.0 \
  --remote https://github.com/example/example-app.git
```

Show version and help:

```bash
bash tools/git-init.sh --help
bash tools/git-init.sh --version
```

### Options

- `-h`, `--help`: prints the version and usage information, then exits.
- `--version`: prints the script version, then exits.
- `-v`, `--verbose`: prints Git commands before running them.
- `-p PATH`, `--path PATH`: target repository root. This option is required.
  The path must be an existing non-empty directory.
- `-r URL`, `--remote URL`: optional remote URL. When provided, the script adds
  it as `origin` and runs `git push -u origin main --tags`.
- `-t TAG`, `--tag TAG`: annotated Git tag to create. Defaults to `v1.0.0`.
  The tag must be a SemVer tag prefixed with `v`.

### Exit Status

- `0`: help or version was shown, the user cancelled safely, or initialization
  completed successfully.
- `1`: an argument was invalid, the target directory was invalid, Git metadata
  was unreadable, the repository already had commits, the tag already existed,
  no committable files were found, Commitlint or a Git hook failed, Git failed,
  or another checked failure occurred.

### Appendix

Review the file preview before confirming the commit. If risky paths are
reported, inspect them carefully and cancel unless they are intentional.

The target must contain readable and executable `.githooks/commit-msg` and a
readable `commitlint.config.cjs`. Install Commitlint and every tool required by
the target hooks before initialization. Any Commitlint or hook failure blocks
`HEAD`, the tag, and the optional push.

Use `--remote` only after checking that the target remote URL is correct. When
`--remote` is omitted, the initializer creates only local Git history.

Run from Bash 4 or newer. On Windows, the PowerShell initializer may be easier
when the target path is a native Windows path.

## verify-repository-audit-runs.py

### Features

- Queries and paginates GitHub Actions through the authenticated `gh` CLI
  without mutation.
- Selects runs by workflow ID, `push` event, exact SHA, expected ref, and
  inclusive creation timestamp.
- Requires exactly one completed successful run for every repeated `--ref`.
- Rejects missing, ambiguous, failed, cancelled, skipped, or neutral runs.
- Ignores manual, scheduled, stale, unrelated-workflow, and unrelated-ref runs.

### Synopsis

```text
usage: verify-repository-audit-runs.py [-h] [--version] [--dry-run] [-v]
                                       --repository OWNER/REPO
                                       --workflow-id ID --sha SHA --ref REF
                                       --created-after UTC
                                       [--timeout-seconds SECONDS]
                                       [--poll-seconds SECONDS]
```

### Description

`verify-repository-audit-runs.py` is the read-only CI gate used by the guarded
release skill before a tag and after the final atomic push. It prevents a green
run for the same SHA from masking a failed required run on another ref. The
caller resolves the exact `Repository audit` workflow ID, records the UTC time
immediately before the corresponding push, and supplies every expected branch
or tag with a separate `--ref` argument. Every `gh api` subprocess receives at
most 30 seconds and never more than the remaining global timeout.

### Usage/Examples

Preview a preflight verification without contacting GitHub:

```bash
python tools/verify-repository-audit-runs.py \
  --dry-run \
  --repository example/project \
  --workflow-id 123456 \
  --sha 0123456789abcdef0123456789abcdef01234567 \
  --ref codex/release-preflight-v1.2.3-0123456 \
  --created-after 2026-08-02T12:00:00Z
```

Wait for both final push runs:

```bash
python tools/verify-repository-audit-runs.py \
  --repository example/project \
  --workflow-id 123456 \
  --sha 0123456789abcdef0123456789abcdef01234567 \
  --ref main \
  --ref v1.2.3 \
  --created-after 2026-08-02T12:05:00Z
```

### Options

- `-h`, `--help`: shows help and exits.
- `--version`: prints `v1.0.0` and exits.
- `--dry-run`: prints the side-effect-free verification plan without querying
  GitHub.
- `-v`, `--verbose`: prints timestamped polling details.
- `--repository OWNER/REPO`: selects the GitHub repository.
- `--workflow-id ID`: selects the resolved numeric workflow ID.
- `--sha SHA`: selects the exact 40-character target commit SHA.
- `--ref REF`: declares one expected branch or tag; repeat as needed.
- `--created-after UTC`: rejects runs created before the inclusive
  `YYYY-MM-DDTHH:MM:SSZ` lower bound.
- `--timeout-seconds SECONDS`: sets the maximum wait, default `600`.
- `--poll-seconds SECONDS`: sets the polling interval, default `5`.

### Exit Status

- `0`: help, version, dry-run, or every expected run succeeded.
- `1`: arguments, access, GitHub response, run identity, timeout, or run
  conclusion failed validation.

### Appendix

The tool requires Python 3, `gh`, authenticated read access to Actions, and a
workflow ID resolved independently from the tracked workflow path. It never
reruns or cancels a workflow. Treat every nonzero exit as a release blocker.

## quality/check-versions.py

`quality/check-versions.py` detects drift between `quality/versions.json` and
the locked Python, Node, and quality-policy declarations. The default check is
declarative: it validates the registry, requirements and package locks,
integrity metadata, and the configured coverage threshold without installing,
downloading, or modifying anything.

### Synopsis

```text
usage: python tools/quality/check-versions.py [--quality-root PATH] [--runtime]
```

`--quality-root PATH` selects another quality configuration directory. The
default is the script directory. `--runtime` additionally checks installed
Python distributions, packages under `tools/quality/node_modules`, and the
registry-owned external tools through bounded local version probes. It does
not install missing tools.

### Exit Status

- `0`: every selected declaration and runtime check matched.
- `1`: a declaration, policy, lock, integrity digest, or runtime version did
  not match.
- `2`: command-line argument parsing failed.

## quality/install-external-tools.py

`quality/install-external-tools.py` installs registry-pinned external quality
tools for one supported runner platform. It uses only the Python standard
library. `RUNNER_TEMP` must name an existing directory without symbolic links,
and the new installation root must be strictly below it.

### Synopsis

```text
usage: python tools/quality/install-external-tools.py \
  --platform {linux-x64,windows-x64} \
  --install-root PATH \
  [--tool {actionlint,shfmt,PSScriptAnalyzer,shellcheck}]
```

Repeat `--tool` to select multiple compatible tools. When it is omitted, the
installer selects every registry tool available for the chosen platform. It
downloads only from credential-free HTTPS locations, verifies the declared
SHA-256 digest before extraction, rejects unsafe archive layouts, stages all
selected tools, and runs their exact version probes. The final installation
root is published only after every probe succeeds.

Selecting PSScriptAnalyzer, including through the default compatible-tool
selection on either platform, requires `pwsh` with PowerShell 7.4.6 or newer.
The installer stages and publishes to a new destination only below
`RUNNER_TEMP` and does not invoke Git. Callers must keep `RUNNER_TEMP` and
`--install-root` outside tracked repository content.

### Exit Status

- `0`: every selected tool was verified and installed.
- `1`: registry, path, download, digest, archive, installation, or probe
  validation failed.
- `2`: command-line argument parsing failed.

## repository-audit.sh

### Features

- Dispatches the shared local and CI audit suite through focused modules for
  common services, contracts, hooks, security, smoke tests, and profiles.
- Defaults to the exhaustive audit profile.
- Maps `all`, `full`, and `static` to the same exhaustive profile without
  repeating Markdown or spelling checks.
- Provides a fast profile for declarations, Git whitespace and line endings,
  Bash and Node syntax, Ruff, and Mypy, plus a focused PowerShell static check,
  read-only checks, and the three Git-hook profiles.
- Checks Markdown, spelling, whitespace, Bash, Python, PowerShell, YAML,
  workflows, secret-scanner configuration, cross-language SemVer patterns,
  release contracts, tests, coverage, and commit messages.
- Resolves new-ref and stable-tag commit ranges from the highest reachable
  stable tag, including all reachable commits for a first release.
- Exercises exact message-file commits through the forced `commit-msg` hook in
  isolated temporary repositories.
- Uses installed, registry-pinned dependencies and never installs Python,
  Node, or external tools from an audit profile.
- Uses WSL-aware temporary paths when Windows PowerShell is invoked from WSL.
- Resolves repository-local Node package executables before commands on
  `PATH`.

### Synopsis

```text
usage: bash tools/repository-audit.sh [mode]

modes:
  all                run the exhaustive profile, default
  full               alias for all
  static             alias for all
  readonly           run installed-tool read-only checks without smoke tests
  markdown           run Markdown lint only
  spelling           run Codespell only
  fast               run declaration and fast static checks
  powershell-static  run PSScriptAnalyzer on tracked .ps1 files
  hook-pre-commit    validate staged content for pre-commit
  hook-commit-msg    validate one commit-message file
  hook-pre-push      validate affected pushed objects and release tags
  -h, --help, help   show help
```

### Description

`repository-audit.sh` is the thin source-of-truth dispatcher. It loads
`common.sh`, `contracts.sh`, `hooks.sh`, `security.sh`, `smoke.sh`, and
`profiles.sh` from `tools/repository-audit/`; those modules own the checks and
profile composition.

The default `all` mode, `full`, and `static` all execute one exhaustive
profile. It includes the declaration and runtime version gate, Markdown,
spelling, YAML and workflow checks, language-specific static analysis,
contracts, coverage, behavior tests, smoke tests, and commit-range validation.
A zero `before` SHA uses the highest reachable stable tag, excluding the tag
currently being audited; without an earlier stable tag, all reachable commits
are checked.

`fast` validates declarations, Git whitespace and line endings, Bash and Node
syntax, Ruff, and Mypy. It intentionally omits runtime version checks,
PSScriptAnalyzer, coverage, behavior tests, and smoke tests.
`powershell-static` runs PSScriptAnalyzer against tracked `.ps1` files.
`readonly` uses installed tools, disables optional Git locks, and avoids
network access, temporary files, and mutating smoke tests.

The hook profiles expose the same implementation used by `.githooks`.
`hook-pre-commit` checks relevant staged files from an isolated index snapshot.
`hook-commit-msg MESSAGE_FILE` validates the message file named by its required
positional argument. `hook-pre-push [REMOTE_NAME REMOTE_URL]` reads one or more
`LOCAL_REF LOCAL_OBJECT_ID REMOTE_REF REMOTE_OBJECT_ID` quadruplets from
standard input, runs affected test families from the exact pushed objects with
a 180-second timeout per selected family, and validates new SemVer release tags.

### Prerequisites

Install the locked Python and Node dependencies before running an exhaustive
profile:

```bash
python -m pip install \
  --disable-pip-version-check \
  --no-input \
  --require-hashes \
  --requirement tools/quality/requirements.lock
npm ci --ignore-scripts --prefix tools/quality
```

The external versions declared in `tools/quality/versions.json` must also be
installed. Audit profiles never run these installation commands or download
tools. Smoke tests require the locked `jsonschema` package and stop with the
installation command when it is absent.

In GitHub Actions, each isolated quality job installs the Python and npm locks
once and invokes the external-tool installer once for the tools compatible with
its platform. The workflow uses no generic dependency cache and no Go setup or
dynamic `go install`; every external binary or module comes from the registry
entry whose HTTPS artifact digest and runtime probe were validated.

Only the exhaustive profile's release-package smoke test uses network access.
It requests `releases/latest` metadata for `asphyx0r/agent-coding-rules` from
the GitHub API and includes `GITHUB_TOKEN` when that environment variable is
set. It does not download release assets or dependencies. The other checks
consume local repository content and installed dependencies.

### Usage/Examples

Run the default full audit:

```bash
bash tools/repository-audit.sh
```

Run the optional read-only audit:

```bash
bash tools/repository-audit.sh readonly
```

Run only Markdown checks:

```bash
bash tools/repository-audit.sh markdown
```

Run only spelling checks:

```bash
bash tools/repository-audit.sh spelling
```

Run static checks and smoke tests:

```bash
bash tools/repository-audit.sh static
```

Run the fast declaration and static subset:

```bash
bash tools/repository-audit.sh fast
```

Run PSScriptAnalyzer against tracked PowerShell scripts:

```bash
bash tools/repository-audit.sh powershell-static
```

### Options

- `all`, `full`, `static`: run the same exhaustive profile. `all` is the
  default when no mode is provided.
- `readonly`: runs non-mutating checks with installed tools.
- `markdown`: runs `markdownlint-cli2` against repository Markdown files.
- `spelling`: runs Codespell with the repository configuration.
- `fast`: runs declaration checks and the fast static subset without runtime
  probes, PSScriptAnalyzer, or coverage.
- `powershell-static`: runs PSScriptAnalyzer on tracked `.ps1` files.
- `hook-pre-commit`: validates relevant staged files.
- `hook-commit-msg MESSAGE_FILE`: validates the required commit-message file.
- `hook-pre-push [REMOTE_NAME REMOTE_URL]`: reads Git push-update quadruplets
  from standard input and validates the affected pushed objects and release
  tags.
- `-h`, `--help`, `help`: prints usage information, then exits.

### Exit Status

- `0`: the selected audit mode passed, or help was shown.
- Any nonzero status: an unknown mode, missing prerequisite, version mismatch,
  validation, test, smoke check, or hook signal failed. The dispatcher
  propagates the failing check's status; signal-aware hook profiles return
  `129`, `130`, or `143` for `HUP`, `INT`, or `TERM`, respectively. A timed-out
  pre-push test family returns `124`.

### Appendix

Run the audit profile required for the operation before creating a release tag
or GitHub release. Treat any failure as a blocker until the underlying
validation issue is understood and fixed.

The GitHub Actions workflow publishes an aggregate `Repository audit` check
for push, pull request, and published-release runs. Its manual counterpart has
the distinct name `Repository audit (manual)` so a manual success cannot
replace a failed automatic run for branch protection or release validation.

The exhaustive audit needs local tools such as `git`, `bash`, `shellcheck`,
`shfmt`, `actionlint`, a PowerShell command, `python`, and `node`, plus the
locked Python and Node dependencies. On Windows, run the audit with Git Bash.

Use focused modes while diagnosing failures. For example, `markdown` and
`spelling` isolate documentation issues, while `fast` isolates declarative and
fast static checks.

On Windows, Codex may repeatedly create Git processes while a repository is
open, as tracked in
[openai/codex#26812](https://github.com/openai/codex/issues/26812). Treat this
as an external, mitigated defect: before write-sensitive Git operations,
inspect Git processes and lock files from a terminal outside Codex. If the
behavior recurs, close Codex normally. Never terminate a process or remove a
lock automatically; first confirm that it is orphaned and no active process
owns it.
