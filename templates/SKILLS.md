<!--
Template usage rules for Codex:

1. Discover only the skills that actually exist in the repository.
2. Read each skill's SKILL.md file as the authoritative source.
3. Read agents/openai.yaml only when that file exists.
4. Write the generated SKILLS.md file in English.
5. Store the generated file in a repository documentation directory, for example
   `docs/SKILLS.md`; never place it in a skill directory.
6. Do not infer, invent, or expand capabilities beyond the source files.
7. Use repository-relative POSIX paths with forward slashes.
8. Sort skills alphabetically by SKILL_SLUG.
9. Keep the same section order for every skill.
10. List only files and directories that actually exist.
11. Repeat list items and examples only as needed; never pad their count.
12. Omit optional fields and sections when they are not applicable.
13. Do not modify any skill file while generating this document.
14. Do not add generation dates or other volatile metadata.
15. Remove all template comments and unresolved placeholders from the output.

Placeholder convention:
- {{SKILL_NAME}}: human-readable skill name.
- {{SKILL_SLUG}}: technical skill identifier or directory name.
- {{SKILL_PATH}}: repository-relative path to the skill directory.
- {{SKILL_SUMMARY}}: concise statement of the skill's purpose.
-->

# Skills

This file is a documentation-only inventory of the skills available in this
repository. It is not loaded or executed by Codex. Each skill's `SKILL.md` file
is the authoritative source for its behavior and instructions.

## Available skills

| Skill                  | Purpose             | Path             |
| ---------------------- | ------------------- | ---------------- |
| **{{SKILL_NAME}}**     | {{SKILL_SUMMARY}}   | `{{SKILL_PATH}}` |

<!-- Repeat one table row and one complete skill section for each skill. -->

## {{SKILL_NAME}}

- **Slug:** `{{SKILL_SLUG}}`
- **Path:** `{{SKILL_PATH}}`
- **Invocation:** `${{SKILL_SLUG}}`

<!-- Omit Invocation when explicit invocation is not supported. -->

{{SKILL_SUMMARY}}

### When to use

- {{USE_CASE}}

<!--
Include this section only when a material scope overlap or misuse risk exists.

### When not to use

- {{EXCLUDED_USE_CASE}}
-->

### Key capabilities

- {{CAPABILITY}}

### Usage examples

```text
{{USAGE_EXAMPLE}}
```

### Contents

```text
{{ACTUAL_SKILL_DIRECTORY_TREE}}
```

<!--
Include Dependencies only when the skill requires external tools, services,
runtimes, packages, environment variables, or repository components.

### Dependencies

- {{DEPENDENCY}}
-->

<!--
Include Limitations only when a material operational, environmental, or scope
constraint must be documented.

### Limitations

- {{LIMITATION}}
-->
