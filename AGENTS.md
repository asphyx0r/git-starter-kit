# Agent instructions

This repository is a generic Git starter kit. It should stay small, explicit,
and easy to reuse.

## Working rules

- Read the existing repository context before making changes.
- State assumptions when a request is ambiguous.
- Ask for clarification when ambiguity blocks safe progress.
- Keep changes minimal and directly tied to the requested task.
- Avoid speculative features, project-specific tooling, or language-specific
  defaults unless explicitly approved.
- Match the style of existing files.
- Do not refactor, rename, delete, or reformat unrelated files.
- Do not commit secrets, tokens, passwords, or real environment values.

## Documentation rules

- Use English for standard GitHub and developer-facing files unless another
  language is explicitly requested.
- Keep documentation concise and operational.
- Update the repository file inventory when files are added, changed,
  deferred, or rejected.

## Verification rules

- Prefer read-only inspection before editing.
- After changes, verify the expected files exist and no unrelated files
  changed.
- Do not run formatters, generators, or automatic fixers unless explicitly
  approved.
