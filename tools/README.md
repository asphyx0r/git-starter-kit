# Tools

<!-- markdownlint-disable MD024 -->

This directory contains small repository management tools for the Git starter
kit. Each tool is documented as an operational reference: what it does, how to
run it, which options it accepts, how it exits, and what practices keep usage
safe.

## build-release-package.ps1

### Features

- Builds an enriched Git starter kit ZIP package.
- Copies tracked starter-kit files into a temporary staging directory.
- Overlays required coding-agent rule files from `agent-coding-rules`.
- Writes `_agent-rules-source.json` with requested and resolved rule metadata.
- Verifies required files before and after ZIP creation.
- Emits GitHub Actions outputs when `GITHUB_OUTPUT` is set.

### Synopsis

```text
usage: powershell -NoProfile -File tools\build-release-package.ps1 [options]

options:
  -RepositoryRoot PATH        repository root to package
  -OutputDirectory PATH       directory where the ZIP is written
  -PackageName NAME           ZIP file name, with .zip appended if needed
  -StarterRef REF             starter-kit ref recorded in the manifest
  -AgentRulesRepository NAME  owner/name repository for agent rules
  -AgentRulesRef REF          latest or SemVer agent-rules tag
```

### Description

`build-release-package.ps1` creates the release asset used by the
`Release package` GitHub Actions workflow. It packages files reported by
`git ls-files`, then copies the required coding-agent rule files from a
resolved `agent-coding-rules` release. The generated ZIP includes the normal
starter-kit content, the required rule files, and `_agent-rules-source.json`.

The script resolves `-AgentRulesRef latest` through the GitHub releases API.
An explicit `-AgentRulesRef` must be a SemVer tag prefixed with `v`.
Branch names and other refs are rejected to keep package inputs reproducible.

### Usage/Examples

Create a local test package in the ignored `.tmp/` directory:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
  -StarterRef local-test `
  -OutputDirectory .tmp\release-package-test `
  -PackageName test-release-package.zip
```

Create a package with a specific agent-rules release:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
  -StarterRef v1.5.0 `
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
  `git-starter-kit-{StarterRef}-with-agent-rules.zip`. If the provided name
  does not end with `.zip`, the extension is appended.
- `-StarterRef REF`: starter-kit ref recorded in the manifest and used in the
  default package name. Defaults to `GITHUB_REF_NAME`; if that is empty, the
  script uses the short current commit SHA.
- `-AgentRulesRepository NAME`: GitHub `owner/name` repository used as the
  agent-rules source. Defaults to `asphyx0r/agent-coding-rules`.
- `-AgentRulesRef REF`: agent-rules reference to package. Defaults to
  `latest`. Accepted values are `latest` or a SemVer tag prefixed with `v`.
- `GITHUB_TOKEN`: optional environment variable used as a bearer token for the
  GitHub releases API when resolving `latest`.
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

Use `latest` for normal release automation so the package includes the latest
published full `agent-coding-rules` release. Use an explicit SemVer tag only
when recreating a package from a known rules release.

Treat failures as release blockers. The script verifies both the resolved
agent-rules tag and the generated archive so that a broken package is not
uploaded silently.

## git-init.ps1

### Features

- Initializes an existing non-empty directory as a Git repository.
- Previews committable files before creating target Git metadata.
- Requires explicit confirmation before initialization and commit.
- Warns before committing risky credential, archive, cache, or runtime paths.
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
commit, renames the branch to `main`, and creates an annotated tag. It pushes
only when `--remote` is provided.

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
  existed, no committable files were found, Git failed, or another terminating
  PowerShell error occurred.

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
commit, renames the branch to `main`, and creates an annotated tag. It pushes
only when `--remote` is provided.

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
  no committable files were found, Git failed, or another checked failure
  occurred.

### Appendix

Review the file preview before confirming the commit. If risky paths are
reported, inspect them carefully and cancel unless they are intentional.

Use `--remote` only after checking that the target remote URL is correct. When
`--remote` is omitted, the initializer creates only local Git history.

Run from Bash 4 or newer. On Windows, the PowerShell initializer may be easier
when the target path is a native Windows path.

## repository-audit.sh

### Features

- Runs the shared local and CI repository audit suite.
- Supports full or focused audit modes.
- Checks Markdown, spelling, whitespace, shell scripts, PowerShell parsing,
  SemVer pattern drift, script smoke behavior, and commit messages.
- Bootstraps pinned Markdown and spelling tools during audit runs.
- Exercises release package generation and Git initializer smoke cases.
- Uses WSL-aware temporary paths when Windows PowerShell is invoked from WSL.

### Synopsis

```text
usage: bash tools/repository-audit.sh [mode]

modes:
  all       run markdown, spelling, and static checks, default
  markdown  run Markdown lint only
  spelling  run Codespell only
  static    run static checks and script smoke tests only
  -h        show help
  --help    show help
  help      show help
```

### Description

`repository-audit.sh` is the source of truth for repository validation. GitHub
Actions calls the same script in mode-specific jobs, and maintainers can run it
locally before preparing release tags or GitHub releases.

The `all` mode runs Markdown lint, spelling checks, and static checks. The
`static` mode includes Git whitespace checks, Bash syntax checks, ShellCheck,
PowerShell parsing, SemVer pattern drift checks, script smoke tests, Node
syntax checks, and commitlint validation for introduced commits.

### Usage/Examples

Run the full audit:

```bash
bash tools/repository-audit.sh
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

### Options

- `all`: runs Markdown, spelling, and static checks. This is the default when
  no mode is provided.
- `markdown`: runs `markdownlint-cli2` against repository Markdown files.
- `spelling`: runs Codespell with the repository configuration.
- `static`: runs Git whitespace checks, Bash and ShellCheck checks,
  PowerShell parsing, SemVer drift checks, script smoke tests, Node syntax
  checks, and commitlint checks.
- `-h`, `--help`, `help`: prints usage information, then exits.

### Exit Status

- `0`: the selected audit mode passed, or help was shown.
- `1`: an unknown mode was provided, a required command was missing, a
  validation check failed, a smoke test failed, or a bootstrapped tool failed.

### Appendix

Run the full audit before creating a release tag or GitHub release. Treat any
failure as a blocker until the underlying validation issue is understood and
fixed.

The full audit needs local tools such as `git`, `bash`, `shellcheck`, a
PowerShell command, `python`, `node`, and `npx`. It also needs network access
to npm for Markdown lint bootstrapping, PyPI for Codespell bootstrapping, and
GitHub for the latest `agent-coding-rules` release used in release package
smoke checks.

Use focused modes while diagnosing failures. For example, `markdown` and
`spelling` isolate documentation issues, while `static` isolates script,
configuration, and smoke-test behavior.
