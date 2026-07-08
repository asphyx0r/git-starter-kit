# {TOOL-COLLECTION-NAME}

<!-- markdownlint-disable MD024 -->

<!--
README_TOOLS.md

Purpose:
Use this Markdown template to document a directory that contains a collection
of scripts, command-line tools, maintenance utilities, or small programs.

Design principles:
- Actionable for humans and coding agents.
- Suitable for Bash, PowerShell, Python, compiled binaries, and small CLIs.
- Explicit about exact commands, inputs, outputs, side effects, and exit codes.
- Useful as a README.md for directories such as tools/, scripts/, or bin/.

Codex / coding-agent instructions:
1. Copy this file to the target directory README path, usually
   {TOOLS-DIRECTORY}/README.md.
2. Replace every placeholder using the form {PLACEHOLDER-NAME}.
3. Keep these mandatory sections:
   - Overview
   - Tool Index
   - Requirements
   - Directory Layout
   - Common Usage
   - Tool Reference
   - Verification
   - Maintenance
   - License
4. Duplicate the per-tool reference block for each documented tool.
5. Remove optional sections only when they are not applicable.
6. Do not invent behavior. If the implementation does not expose an item, write
   "Not applicable" or "To be documented".
7. Prefer exact tool names, option names, default values, paths, environment
   variables, exit codes, and help output from the source code.
8. Keep examples executable and copy-paste friendly.
9. After filling the template, verify Markdown rendering and run examples when
   possible.
10. Delete this comment block in finalized user-facing documentation if
   desired.

Placeholder convention:
- Use uppercase placeholders wrapped in braces, for example {TOOL-NAME}.
- Replace placeholders with concrete values before publishing.
- Do not leave unresolved placeholders in final documentation unless explicitly
  marked as "To be documented".
-->

{TOOL-COLLECTION-SUMMARY}

## Overview

{OVERVIEW}

Describe what this tool directory is for, who should use it, and when these
tools should be run.

Include the following information when relevant:

- main workflows supported by the tools;
- required repository state before running tools;
- operating systems or shells supported;
- network access;
- files, directories, Git state, or remote systems that tools can modify;
- safety expectations before running destructive or publishing commands.

## Tool Index

| Tool | Purpose | Runtime | Safe default |
| --- | --- | --- | --- |
| `{TOOL-1-PATH}` | {TOOL-1-PURPOSE} | `{TOOL-1-RUNTIME}` | {yes/no} |
| `{TOOL-2-PATH}` | {TOOL-2-PURPOSE} | `{TOOL-2-RUNTIME}` | {yes/no} |
| `{TOOL-3-PATH}` | {TOOL-3-PURPOSE} | `{TOOL-3-RUNTIME}` | {yes/no} |

Safe default means the tool can be run without modifying tracked files,
publishing data, deleting data, changing Git history, or contacting remote
services.

## Requirements

| Requirement | Version | Required | Used by | Description |
| --- | ---: | ---: | --- | --- |
| `{RUNTIME-OR-TOOL}` | `{VERSION}` | yes | `{TOOL-NAME}` | {DESCRIPTION} |
| `{DEPENDENCY}` | `{VERSION}` | {yes/no} | `{TOOL-NAME}` | {DESCRIPTION} |

If no external requirements exist, state this explicitly:

```text
No external requirements. Run the tools directly from the repository.
```

## Directory Layout

```text
{TOOLS-DIRECTORY}/
  README.md
  {TOOL-1-FILE}
  {TOOL-2-FILE}
  {SUPPORTING-FILE-OR-DIRECTORY}
```

Document generated files, temporary directories, and files that should not be
edited manually.

## Common Usage

Run commands from the repository root unless a tool says otherwise.

```bash
{COMMON-COMMAND-1}
{COMMON-COMMAND-2}
```

Use explicit runtime invocations for scripts:

```bash
bash {TOOLS-DIRECTORY}/{SCRIPT-NAME}.sh [OPTIONS]
python {TOOLS-DIRECTORY}/{SCRIPT-NAME}.py [OPTIONS]
pwsh {TOOLS-DIRECTORY}/{SCRIPT-NAME}.ps1 [OPTIONS]
```

## Tool Reference

## {TOOL-1-NAME}

### Purpose

`{TOOL-1-NAME}` - {TOOL-1-ONE-LINE-DESCRIPTION}

{TOOL-1-DETAILED-DESCRIPTION}

### Synopsis

```bash
{TOOL-1-COMMAND} [OPTIONS] {ARGUMENTS}
```

For scripts requiring an interpreter, use the explicit runtime invocation:

```bash
{INTERPRETER} {TOOL-1-PATH} [OPTIONS] {ARGUMENTS}
```

### Examples

#### {TOOL-1-EXAMPLE-1-TITLE}

```bash
{TOOL-1-EXAMPLE-1-COMMAND}
```

{TOOL-1-EXAMPLE-1-EXPLANATION}

Expected result:

```text
{TOOL-1-EXAMPLE-1-EXPECTED-OUTPUT}
```

#### {TOOL-1-EXAMPLE-2-TITLE}

```bash
{TOOL-1-EXAMPLE-2-COMMAND}
```

{TOOL-1-EXAMPLE-2-EXPLANATION}

Expected result:

```text
{TOOL-1-EXAMPLE-2-EXPECTED-OUTPUT}
```

### Options

| Option | Argument | Required | Default | Description |
| --- | --- | ---: | --- | --- |
| `-h`, `--help` | none | no | none | Show help message and exit. |
| `{OPTION}` | `{ARGUMENT}` | {yes/no} | `{DEFAULT}` | {DESCRIPTION} |

If the tool has no options, write `No options.` under this section.

### Arguments

| Argument | Required | Default | Description |
| --- | ---: | --- | --- |
| `{ARGUMENT}` | {yes/no} | `{DEFAULT}` | {DESCRIPTION} |

If the tool has no positional arguments, write `No positional arguments.` under
this section.

### Inputs

| Input | Type | Required | Description |
| --- | --- | ---: | --- |
| `{INPUT-NAME}` | `{FILE/DIRECTORY/VALUE/STDIN}` | {yes/no} | {DESCRIPTION} |

If the tool consumes no files, directories, standard input, or external values,
write `No external inputs.` under this section.

### Outputs

| Output | Type | Description |
| --- | --- | --- |
| `{OUTPUT-NAME}` | `{FILE/DIRECTORY/STDOUT/STDERR/EXIT-CODE}` | {DESCRIPTION} |

If the tool produces no files, directories, standard output, or standard error,
write `No external outputs.` under this section.

### Files

| Path | Required | Read | Write | Description |
| --- | ---: | ---: | ---: | --- |
| `{PATH}` | {yes/no} | {yes/no} | {yes/no} | {DESCRIPTION} |

### Environment

| Variable | Required | Default | Description |
| --- | ---: | --- | --- |
| `{ENVIRONMENT-VARIABLE}` | {yes/no} | `{DEFAULT}` | {DESCRIPTION} |

If no environment variables affect behavior, write `Not applicable.` under this
section.

### Safety and Side Effects

{SAFETY-AND-SIDE-EFFECTS-DESCRIPTION}

Document whether the tool can:

- create files;
- overwrite files;
- delete files;
- modify permissions;
- modify Git history;
- call remote services;
- expose secrets;
- require elevated privileges.

### Exit Status

| Code | Meaning | Typical Cause | Recommended Action |
| ---: | --- | --- | --- |
| `0` | Success. | Command completed successfully. | No action required. |
| `1` | Generic error. | Unexpected failure. | Check logs and arguments. |
| `{CODE}` | {MEANING} | {CAUSE} | {ACTION} |

## Troubleshooting

| Problem | Probable Cause | Resolution |
| --- | --- | --- |
| `{PROBLEM}` | {CAUSE} | {RESOLUTION} |

## Verification

Use this section to document how to verify the tool collection after
installation, modification, or release packaging.

```bash
{VERIFICATION-COMMAND-1}
{VERIFICATION-COMMAND-2}
```

Expected result:

```text
{EXPECTED-VERIFICATION-OUTPUT}
```

## Maintenance

{MAINTENANCE-NOTES}

Include when relevant:

- owner or maintainer;
- expected update process;
- release process;
- generated files that should not be edited manually;
- compatibility rules that must remain stable.

## License

{LICENSE-INFORMATION}

<!--
Finalization checklist for Codex / coding agents:
- [ ] Every placeholder has been replaced or intentionally marked.
- [ ] Mandatory sections are present.
- [ ] The Tool Index lists every maintained tool in the directory.
- [ ] Each per-tool reference matches the implementation.
- [ ] Examples have been executed when possible.
- [ ] Options, arguments, inputs, outputs, and exit codes match the source.
- [ ] Safety and side effects are documented for mutating tools.
- [ ] Markdown rendering has been checked.
- [ ] markdownlint has been run when available.
-->
