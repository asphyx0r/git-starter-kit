# Project configuration

`.starter-kit-project.json` is read by the shared `tools/project_config.py`
parser. An existing malformed or inaccessible file fails. New projects default
to `repositoryRole: project`, `releaseKind: repository`, no declared checks and
all three optional automations disabled. Disabled automations do not disable
mandatory rule instructions, ordinary core audits, hooks or release artifacts.

## Application checks

Add reviewed explicit argv arrays, working directories relative to the repository
root and supported platforms. For a project with a real `scripts/test.py`:

```json
{
  "name": "application tests",
  "argv": ["python", "scripts/test.py"],
  "workingDirectory": ".",
  "platforms": ["linux", "windows"]
}
```

This object belongs in the `checks` array; do not adopt commands until the
application implements them. There is no language detection or generic test
discovery. Core ownership uses exact `_starter-kit-files.json` paths; application
files inside `tools/` or `tests/` remain application-owned.

```bash
bash tools/repository-audit.sh project-checks --dry-run
bash tools/repository-audit.sh project-checks
```

The first command reports a plan without executing it. The second executes
eligible commands with timeouts and contained working directories; missing
commands, bad paths and failed checks block. CI runs declared commands on the
verified PR head or event revision. Full/readonly local audits only show a plan.
Empty checks warn and cannot be described as passed application regression tests.

## Ignore policy

The root `.gitignore` provides Bash, PowerShell, Perl, Python, Java, Rust, Go,
Laravel, JavaScript and C/C++ sections. These headings are comments: they do
not limit a pattern to that language or directory. A leading `/` anchors a
pattern to the directory containing that `.gitignore`.

Active starter output locations are `/.venv/` for the documented Python
environment, `/.tmp/` for local audit/package scratch files,
`/tools/quality/node_modules/` for locked Node tools, and
`/tools/quality/external/` for an explicitly chosen local external-tool root.
That last path is an example installation destination, not an implicit default
or an automatic installation. Other files in `tools/quality/` remain trackable.
Use the [local external installer](../tools/README.md) with
explicit `--local`, platform, absent root and selected `--tool` capabilities.
Its session-only search paths supplement the existing locked Python/Node setup;
application runtimes and dependencies remain project-owned.
Active local defaults also exclude editor recovery files (`*.swp`, `*.swo`, and
`*~`) at every depth, plus root-only `/.env`, `/.env.local`, `/.netrc`,
`/.pypirc`, and local IntelliJ state under `/.idea/`. Root-only rules do not
apply to nested applications, which must define their own local secret policy
before generating credentials. Shared IDE configuration, `.vscode/mcp.json`,
`*.code-workspace`, `/.envrc`, `/.npmrc`, certificate and environment fixtures,
and optional project-owned credential paths remain trackable unless a project
explicitly activates a contextual rule.

Contextual exclusions stay commented. Activate them only after identifying
generated outputs in your project, preferably as exact rooted paths or in the
application's own `.gitignore`. General `build/`, `dist/`, `vendor/`, `log/`,
`env/`, `ENV/`, archive extensions and binary extensions can hide sources or
fixtures. Never rely on tracked files as evidence: ignore rules affect new
untracked files. Test representative new paths with `git check-ignore --quiet`
(exit 0 means ignored, exit 1 means trackable), using `--verbose` separately to
diagnose the matching pattern. Check case variants on your supported hosts.
Keep legitimate sources, sanitized test fixtures, archive/binary fixtures and
Go, Cargo, Composer and frontend lockfiles available for version control.

## Laravel onboarding

Initialize the starter system first, including its system-only commit and
annotated `v1.0.0`. Then create a Laravel application into an absent or empty
`laravel/`, from the repository root:

```bash
composer create-project --prefer-dist --remove-vcs laravel/laravel laravel
```

Do not run Composer's project creation in the already populated root. Keep
the root system configuration in place; do not merge or move its files into
the application. `--remove-vcs` removes the application's downloaded VCS
metadata, leaving the root `.git` as the single repository. The resulting code
lives in `laravel/app`, application tests in `laravel/tests`, and the deployed
web document root must be `laravel/public`, never the repository or application
root. Run subsequent Composer, Artisan and npm commands from `laravel/`.
Preserve the generated `laravel/.gitignore` independently from the root policy;
review its local secrets and generated outputs before staging application files.
Keep `laravel/.env` and generated private keys untracked, while committing the
sanitized `.env.example`, application sources and dependency lockfiles.

The generic credential rule can flag a PHP variable reference in Laravel's
generated `UserFactory`, where the `password` field uses `static::$password`.
Review the finding; for this case, compute the existing hash in a local `$hash`
variable and return it for that field, preserving the factory's behavior.
Rerun the application tests and scanner after this targeted adjustment; keep
the secret checks enabled without adding suppressions or allowlists.

Install PHP, required PHP extensions and Composer compatible with the desired
framework and skeleton release. As of September 12, 2026, Laravel 13 requires
PHP 8.3 or newer; Laravel 12 supports PHP 8.2 through 8.5. Do not bypass Composer
platform requirements. Composer accepts an optional version argument after the
destination; for a pinned PHP 8.2-compatible skeleton example:

```bash
composer create-project --prefer-dist --remove-vcs laravel/laravel laravel 12.12.2
```

Choose a supported version for your project and record both the selected skeleton
and the resolved framework/dependency lock versions. Pinning the skeleton alone
does not fix every dependency version.
See the official [Composer create-project reference][composer-create-project],
[Laravel release compatibility][laravel-releases] and
[pinned Laravel 12 skeleton requirements][laravel-skeleton].

For an application that uses Artisan tests, this illustrative `checks` entry
runs with `workingDirectory` set to `laravel`:

```json
{
  "name": "Laravel tests",
  "argv": ["php", "artisan", "test"],
  "workingDirectory": "laravel",
  "platforms": ["linux", "windows"]
}
```

Adopt it only after preparing dependencies in the environment running the check.
Pre-push validation uses an exact Git revision snapshot and does not inherit
ignored `laravel/vendor/` or `laravel/node_modules/` from a developer worktree.
Provide a project-owned setup/test script or CI job that explicitly installs
locked dependencies with `composer install` inside `laravel/`, prepares its
test environment, and runs the application tests. When frontend checks need
Node dependencies, explicitly arrange the lockfile-appropriate installation
there too. For pre-push checks, declare a project-owned command that performs
the required setup in its snapshot; a CI install alone does not prepare that
separate local snapshot. Missing dependencies remain blocking failures.

[composer-create-project]: https://getcomposer.org/doc/03-cli.md#create-project
[laravel-releases]: https://laravel.com/docs/13.x/releases
[laravel-skeleton]: https://github.com/laravel/laravel/blob/945f4e5a9fd3695dc0ee512f497c650fb82cfbb8/composer.json

## Optional automations

`agentRulesSync`, `guardedMerge` and `releasePreflight` are explicit Boolean
flags. Activate only after reviewing the project policy, publishing workflow
changes and configuring any required GitHub App credentials and repository
protections. Privileged activation is read from an immutable default-branch
snapshot, while target release metadata comes from its own target snapshot.

Manual intentional agent-rule updates remain supported when automatic sync is
false. Enabled guarded merge keeps exact protected validation; disabled mode
uses the authorized ordinary review/squash path. Dedicated release preflight
is selected only when enabled; ordinary target/tag audit proof is unconditional.
See [Guarded merges](guarded-pull-request-merges.md) for the enabled mechanism.

## Existing project updates

The companion upgrade toolkit embeds the exact candidate initialization ZIP.
Its read-only planning command uses `--dry-run`; ordinary planning writes a
journal. Review conflicts and obsolete-file preservation before applying a patch.
Agent rules remain delegated to the official rule updater. New settings are
`initialize-only`: missing settings require manual review/initialization;
existing settings are preserved. Absence keeps explicit legacy behavior and
never silently activates the new disabled defaults.

Before integrating a downstream patch, inventory the application's actual prior
validation commands and CI jobs and preserve an equivalent project-owned path.
If it relied on former generic discovery, adopt reviewed explicit checks or
retain equivalent project CI as a separate application migration. The updater
cannot infer commands; flags and an empty-check warning do not prove equivalence.
