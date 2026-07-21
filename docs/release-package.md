# Release Package

## Purpose

This repository can publish an enriched release package for people who want to
start a new project with the Git starter kit and the coding-agent rules already
included.

The agent rules come from
[agent-coding-rules](https://github.com/asphyx0r/agent-coding-rules), a
repository that provides practical behavior and code-quality rules for AI
coding agents.

GitHub always adds two source archives to each release:

- `Source code (zip)`
- `Source code (tar.gz)`

Those archives contain only the files that are committed in `git-starter-kit`
at the release tag.

The release package workflow adds one more downloadable file to the same
release. This extra ZIP overlays a resolved `agent-coding-rules` release on top
of the starter kit files.

## Generated File

The generated asset is named like this:

```text
git-starter-kit-vX.Y.Z-with-agent-rules.zip
```

The ZIP includes the normal starter kit files plus these files from
`agent-coding-rules`:

- `AGENTS.md`
- `CODING_RULES.md`
- `COMMIT_RULES.md`
- `DOCUMENTATION_RULES.md`
- `LANGUAGE_RULES.md`
- `RELEASE_RULES.md`

The ZIP also includes `_agent-rules-source.json`. This manifest records where
the agent rules came from, including the requested reference, resolved release
tag, commit SHA, and release date.

## GitHub App Authentication

Resolving agent-rules releases across repositories uses a GitHub App installed
on `agent-coding-rules` with read-only **Contents** permission. Configure these
Actions values in `git-starter-kit`:

- Repository variable `AGENT_RULES_APP_CLIENT_ID`
- Repository secret `AGENT_RULES_APP_PRIVATE_KEY`

The workflow generates a short-lived installation token and passes it only to
the package build step. The built-in workflow token remains responsible for
uploading the generated asset to the `git-starter-kit` release.

## Automatic Release Mode

Use this mode for the normal release process.

1. Prepare the release commit in `git-starter-kit`.
2. From a clean repository, run `bash tools/repository-audit.sh` locally.
3. Stop if the local audit fails; do not create a release tag or release.
4. Create and push the release tag, for example `v1.3.0`.
5. On GitHub, open the repository page.
6. Open **Releases**.
7. Create a new release from the tag.
8. Publish the release.

After the release is published, GitHub starts the `Release package` workflow
automatically. Automatic releases intentionally use `latest` so the package
always includes the latest published full `agent-coding-rules` release.

The workflow then:

1. Checks out `git-starter-kit` at the published release tag.
2. Resolves `latest` to the latest published full `agent-coding-rules` release.
3. Verifies that the cloned agent rules checkout matches the resolved tag.
4. Copies the tracked starter-kit files into a temporary package folder.
5. Copies the six agent rule files into that package folder.
6. Writes `_agent-rules-source.json` with the requested and resolved
   agent-rules references.
7. Creates the ZIP file.
8. Verifies that the required files are present in the ZIP.
9. Uploads the ZIP to the GitHub release as a release asset.

When the workflow finishes, the GitHub release should show an asset such as:

```text
git-starter-kit-v1.3.0-with-agent-rules.zip
```

Download this ZIP when you want a ready-to-use starter kit with agent rules
already included.

## Manual Release Mode

Use this mode when you need to create or recreate the enriched package for an
existing release.

The release must already exist on GitHub before running the workflow manually.
The `tag` input must be an existing GitHub release tag that uses SemVer with a
leading `v`, for example `v1.3.0`. The manual workflow uploads an asset to
that release; it does not create the release itself.

1. Open the `git-starter-kit` repository on GitHub.
2. Open the **Actions** tab.
3. Select the **Release package** workflow.
4. Click **Run workflow**.
5. Fill in `tag` with the release tag to package, for example `v1.3.0`.
6. Fill `agent_rules_ref` with `latest` or a SemVer `agent-coding-rules` tag,
   for example `v1.36.1`.
7. Click **Run workflow**.

Manual release packages accept `latest` or an explicit SemVer tag. Use a SemVer
tag when you need to recreate a package from a known agent-rules release.
Branch names are still rejected so the generated asset stays reproducible.

When the workflow finishes, open the GitHub release page for the tag and check
that the ZIP asset is listed under the release assets.

## Local Test

Run the full repository audit locally before publishing a release:

```bash
bash tools/repository-audit.sh
```

The full audit intentionally resolves the latest published full
`agent-coding-rules` release during package smoke checks. Treat a failure to
resolve or validate that latest release as an audit failure before publishing.
It also needs network access to npm for Markdown lint bootstrapping and PyPI
for Codespell bootstrapping. Use `markdown`, `spelling`, or `static` when you
need to isolate one audit family.

You can also test only the package generation locally before publishing a release.

From the repository root, run:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
  -StarterRef local-test `
  -OutputDirectory .tmp\release-package-test `
  -PackageName test-release-package.zip
```

Inspect the generated ZIP:

```powershell
tar -tf .tmp\release-package-test\test-release-package.zip
tar -xOf .tmp\release-package-test\test-release-package.zip _agent-rules-source.json
```

The local test creates a ZIP only. It does not upload anything to GitHub.
`AgentRulesRef` defaults to `latest`; pass a SemVer tag only when you need a
known agent-rules release.

The script copies files reported by `git ls-files`. Local untracked files are
not included in the package. This is intentional, because release packages
should be built from committed repository content.

## Troubleshooting

If the release asset is missing, open the **Actions** tab and inspect the latest
`Release package` workflow run.

If the manual workflow fails, check that the `tag` input matches an existing
GitHub release tag using SemVer with a leading `v`.

If the upload fails because the asset already exists, delete the old asset from
the release page and run the workflow again.

If the package must use a specific agent rules version, run the manual
workflow again with an explicit SemVer `agent_rules_ref` value.
