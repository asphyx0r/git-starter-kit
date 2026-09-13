# Your project

This repository starts with shared Git hooks, auditable release artifacts and
explicit application checks. Replace this paragraph with your project's name,
purpose, prerequisites and minimal application usage before publishing it.

## Installation

Download the `with-agent-rules.zip` asset from a published
[starter release](https://github.com/asphyx0r/git-starter-kit/releases), extract
it into a new empty project directory, and run commands from that directory.
The companion `upgrade-toolkit.zip` is for reviewed updates to existing projects.
A source clone is for maintaining the starter itself.

Supported hosts are Windows with Git for Windows Bash and Windows PowerShell
5.1 or PowerShell 7, and Linux with Bash and PowerShell 7 when using `.ps1`
tools. Install Git, Python 3.11 or newer, Node.js 24 and npm before initialization.
The Python installation must provide `venv` and `pip`. If those components are
distributed separately, install them for the interpreter you choose.
Create a local Python environment before initialization:

```bash
python -m venv .venv
```

Activate that interpreter on Linux Bash:

```bash
source .venv/bin/activate
```

On Git for Windows Bash instead:

```bash
source .venv/Scripts/activate
```

Or select it on Windows PowerShell for the current session:

```powershell
$env:PATH = (Resolve-Path .venv/Scripts).Path + ";" + $env:PATH
```

Keep that environment selected for initialization and audits. Install the
existing locked Python dependencies, including the initializer's required
`jsonschema`, and local Node dependencies with the active interpreter:

```bash
python -m pip install --require-hashes --requirement tools/quality/requirements.lock
npm ci --ignore-scripts --prefix tools/quality
```

Provision the external tools selected for your checks on Windows x64 or Linux
x64 with the explicit local installer. See
[Local external tools](tools/README.md#local-external-tools) for pinned installs
and session-only search paths. Audits never install tools automatically.

Check your own Git author identity:

```bash
git config --global --get user.name
git config --global --get user.email
```

If no identity exists, configure your real author name and email before running
the initializer. On Linux or Git for Windows Bash:

```bash
bash tools/git-init.sh --path .
```

Or on Windows PowerShell:

```powershell
powershell -NoProfile -File tools/git-init.ps1 --path .
```

An optional inspection, run before initialization, is:

```bash
bash tools/git-init.sh --path . --dry-run
```

Initialization creates the system commit and annotated `v1.0.0` tag, installs
the local hook path, and prepares repository release artifacts. It does not
publish anything. Add application files after this system initialization.

For Laravel, complete that system-only annotated `v1.0.0` release first.
Install PHP and Composer versions compatible with your selected Laravel release,
then run this from the repository root with `laravel/` absent or empty:

```bash
composer create-project --prefer-dist --remove-vcs laravel/laravel laravel
```

Keep the single root `.git`; application code lives in `laravel/app`, tests in
`laravel/tests`, and the web document root is `laravel/public`. Run application
Composer, Artisan and npm commands inside `laravel/`. Preserve its generated
local `.gitignore` and keep `.env` secrets untracked. See
[Laravel onboarding](docs/project-configuration.md#laravel-onboarding) for version
selection and dependency preparation for checks.

## Usage and validation

```bash
bash tools/repository-audit.sh fast
python -B tools/project_config.py --repository-root .
```

The default `.starter-kit-project.json` has project role, repository release
kind, all optional automations disabled and no application checks. Mandatory
agent instructions, hooks, core audits and artifact validation still apply.
An empty-check warning means application regression validation has not been
configured. Add reviewed commands in `checks`; CI executes them against the
exact checked-out revision. Full local core audits show their read-only plan;
execute them with `bash tools/repository-audit.sh project-checks`.

See [Tools](tools/README.md) for commands and side effects,
[Project configuration](docs/project-configuration.md) for declared checks and
optional automation activation, and [Managed files](docs/repository-files.md)
for the composed inventory. Fill in your application's build/run instructions
and supported runtime versions here once those commands exist.

## Contributing and support

Project maintainers must fill in the project contacts described in
[Contributing](CONTRIBUTING.md), [Support](SUPPORT.md),
[Security](SECURITY.md) and [Code of conduct](CODE_OF_CONDUCT.md).

## License and attribution

The starter's MIT notice is retained in [LICENSE](LICENSE). Preserve it when
redistributing starter content and document your application's license.
[Starter source](https://github.com/asphyx0r/git-starter-kit) and
[agent rule source](https://github.com/asphyx0r/agent-coding-rules) are attribution
links. `_agent-rules-source.json` records the authenticated upstream release,
immutable commit and rule hashes. Project support belongs to your maintainers.
