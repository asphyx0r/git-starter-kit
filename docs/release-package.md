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
release. This extra ZIP overlays the latest stable `agent-coding-rules` files
on top of the starter kit files.

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
the agent rules came from, including the source repository, release tag, commit
SHA, and release date.

## Automatic Release Mode

Use this mode for the normal release process.

1. Prepare the release commit in `git-starter-kit`.
2. Create and push the release tag, for example `v1.3.0`.
3. On GitHub, open the repository page.
4. Open **Releases**.
5. Create a new release from the tag.
6. Publish the release.

After the release is published, GitHub starts the `Release package` workflow
automatically.

The workflow then:

1. Checks out `git-starter-kit` at the published release tag.
2. Finds the latest stable published release of `agent-coding-rules`.
3. Copies the tracked starter-kit files into a temporary package folder.
4. Copies the six agent rule files into that package folder.
5. Writes `_agent-rules-source.json`.
6. Creates the ZIP file.
7. Verifies that the required files are present in the ZIP.
8. Uploads the ZIP to the GitHub release as a release asset.

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
6. Leave `agent_rules_ref` as `latest` to use the latest stable
   `agent-coding-rules` release.
7. Click **Run workflow**.

Use a specific `agent_rules_ref`, such as `v1.36.1`, only when you need to
rebuild the package from an exact `agent-coding-rules` version. Branch names
are rejected so release packages stay reproducible.

When the workflow finishes, open the GitHub release page for the tag and check
that the ZIP asset is listed under the release assets.

## Local Test

You can test the package generation locally before publishing a release.

From the repository root, run:

```powershell
powershell -NoProfile -File scripts\build-release-package.ps1 `
  -StarterRef local-test `
  -AgentRulesRef latest `
  -OutputDirectory .tmp\release-package-test `
  -PackageName test-release-package.zip
```

Inspect the generated ZIP:

```powershell
tar -tf .tmp\release-package-test\test-release-package.zip
tar -xOf .tmp\release-package-test\test-release-package.zip _agent-rules-source.json
```

The local test creates a ZIP only. It does not upload anything to GitHub.

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

If the package uses the wrong agent rules version, run the manual workflow again
with the required `agent_rules_ref`.
