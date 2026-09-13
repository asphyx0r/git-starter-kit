# Project tools

These tools initialize this project, validate its managed core, run declared
application checks and prepare verifiable release artifacts. Run examples from
the repository root and consult each tool's `--help` before mutation.

## Tool index

| Tool | Purpose | Runtime |
| --- | --- | --- |
| `git-init.sh` / `git-init.ps1` | System initialization | Bash / PowerShell |
| `initialize-repository.py` | Initializer helper | Python |
| `project_config.py` | Read strict project settings | Python |
| `project_validation.py` | Core ownership and declared checks | Python |
| `automation_config.py` | Immutable workflow activation adapter | Python |
| `repository-audit.sh` | Core checks and project plan | Bash |
| `release-artifacts.py` | Prepare/check release artifacts | Python |
| `merge-pull-request.py` | Reviewed exact-message squash merge | Python / gh |
| `verify-repository-audit-runs.py` | Exact workflow-run proof | Python / gh |
| `backup-target-directory.py` | Local directory backup | Python |
| `quality/check-versions.py` | Verify pinned tools | Python |
| `quality/install-external-tools.py` | Verified external tool installation | Python |
| `git_objects.py` / `process_runner.py` | Shared runtime modules | Python |

## Requirements

Use Windows or Linux with Git, Python 3.11+, Bash, Node.js 24 and npm.
Windows `.ps1` tools support Windows PowerShell 5.1 or PowerShell 7; Linux `.ps1`
tools require PowerShell 7. Before initialization, create and select the local
Python environment described in [Installation](../README.md#installation).
Use its active `python` for
`python -m pip install --require-hashes --requirement tools/quality/requirements.lock`;
the initializer requires `jsonschema`, not provided by standard Python. Install
locked Node dependencies with `npm ci --ignore-scripts --prefix tools/quality`.
Full/static audits also require the pinned tools in `quality/versions.json` and
PSScriptAnalyzer where PowerShell files are audited. See each CLI's help for
installation roots and platform selection, and
[Local external tools](#local-external-tools). Configure your real Git identity
before initialization. Optional remote operations require GitHub CLI authentication.

The root ignore policy protects the documented `.venv/` and
`tools/quality/node_modules/` setup outputs. `tools/quality/external/` is an
explicit local external-tool destination example; tools do not select it
implicitly or install dependencies during audits. Keep other application files
under `tools/quality/` trackable. See
[Ignore policy](../docs/project-configuration.md#ignore-policy).

## Local external tools

The installer supports native Windows x64 and Linux x64; macOS is unsupported.
Choose the tools required by your checks using repeated `--tool`. The explicit
`--local` mode does not require `RUNNER_TEMP`, change global search paths or
install language runtimes. Selecting PSScriptAnalyzer requires `pwsh` with
PowerShell 7.4.6 or newer already on the current process's `PATH`.

Run from the repository root. `--install-root` is mandatory; the example
`tools/quality/external` must be absent and its parent must already exist.
Existing destinations, unsafe paths, symlinks and junctions are rejected.
All selected artifacts are digest-verified, safely staged and actually probed
before atomic publication. A failed selection or tool blocks the whole install.
Install another selection into a different absent root; installs never append
to or overwrite an existing root.

Inspect a single-tool selection without downloads or writes:

```bash
python -B tools/quality/install-external-tools.py --local --dry-run \
  --platform linux-x64 --install-root tools/quality/external --tool shfmt
```

Use `windows-x64` on Windows. For the five external tools used by full core
audits, an actual Linux install is:

```bash
python -B tools/quality/install-external-tools.py --local \
  --platform linux-x64 --install-root tools/quality/external \
  --tool actionlint --tool shfmt --tool PSScriptAnalyzer \
  --tool shellcheck --tool gitleaks
export PATH="$PWD/tools/quality/external/bin:$PATH"
export PSModulePath="$PWD/tools/quality/external/Modules${PSModulePath:+:$PSModulePath}"
```

For PSScriptAnalyzer on Windows, choose a short installation root when the
repository path is deep: long nested module paths can cause `PathTooLongException`.
Use the same absent root for `--install-root` and the session paths below.

The equivalent Windows PowerShell session is:

```powershell
$installerArguments = @(
    '--local', '--platform', 'windows-x64',
    '--install-root', 'tools/quality/external',
    '--tool', 'actionlint', '--tool', 'shfmt', '--tool', 'PSScriptAnalyzer',
    '--tool', 'shellcheck', '--tool', 'gitleaks'
)
python -B tools/quality/install-external-tools.py @installerArguments
$externalRoot = (Resolve-Path tools/quality/external).Path
$env:PATH = (Join-Path $externalRoot 'bin') + [IO.Path]::PathSeparator + $env:PATH
$env:PSModulePath = (Join-Path $externalRoot 'Modules') + [IO.Path]::PathSeparator + $env:PSModulePath
```

These search-path assignments affect only the current shell and its children.
Success prints `external tools: installation complete`. `--verbose` shows the
selection and destination. `--help` and `--version` are read-only. After selecting
the locked Python/Node environments and all external tools, check them with:

```bash
python -B tools/quality/check-versions.py --runtime
```

This complete runtime check reports missing unselected tools; a partial install
only proves its selected capabilities. The installer shares `versions.json`
with the declaration/runtime checker and resolves the selected platform's
artifact; it does not install Python/Node packages or application dependencies.
Continue using the locked setup above and project-owned runtime/dependency setup
for declared application checks, including Composer inside `laravel/`.

CI callers omit `--local`: the new root remains strictly inside the existing
safe `RUNNER_TEMP`; omitted `--tool` selects all compatible registry tools.

## Directory layout

Managed runtime modules live under `tools/`, `repository-audit/` and `quality/`.
Application tools can use the same directories without becoming starter-owned.
The exact inventory is [Managed files](../docs/repository-files.md).

## Common usage and tool reference

```bash
bash tools/git-init.sh --path . --dry-run
bash tools/git-init.sh --path .
bash tools/repository-audit.sh fast
bash tools/repository-audit.sh project-checks --dry-run
python -B tools/project_config.py --repository-root .
python -B tools/release-artifacts.py --help
python -B tools/quality/install-external-tools.py --help
```

Initialization creates Git state, system release artifacts and the initial tag;
it does not publish. `fast` checks managed core behavior. Full/readonly audits
plan application checks; `project-checks` executes explicit commands and blocks
on failure. Empty checks warn. Release preparation writes artifact metadata;
`--help` is read-only. Backup creates a local archive. Merge execution can write
reviewed GitHub state and requires separate authorization; consult
[Guarded merges](../docs/guarded-pull-request-merges.md).

## Verification

```bash
bash tools/repository-audit.sh fast
bash tools/repository-audit.sh project-checks
```

Core success and successful eligible application checks are separate results.
An empty-check warning never proves application regressions passed.

Prepare application dependencies in the environment that runs each declared
check. Exact pre-push snapshots do not inherit ignored dependencies from your
worktree. A Laravel project-owned setup/test command runs inside `laravel/` and
arranges Composer dependencies and its test environment before Artisan tests;
CI must prepare its own dependencies too. See
[Laravel onboarding](../docs/project-configuration.md#laravel-onboarding).

## Maintenance

Project maintainers own application commands and optional activation in
[Project configuration](../docs/project-configuration.md). Update managed core
with a reviewed companion toolkit patch on a disposable target first; preserve
initialize-only settings, merge conflicts and obsolete files. Agent rules use
the official upstream synchronization workflow, including intentional manual
updates when automatic sync is disabled. Packaging never synchronizes source
rules: stale or unverifiable latest upstream content fails the build.

## License

Preserve the starter's MIT notices in [LICENSE](../LICENSE) and the immutable
provenance in `_agent-rules-source.json`. Project contacts belong in
[Support](../SUPPORT.md) and [Security](../SECURITY.md).
