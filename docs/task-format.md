# Task format and New task form

The CLI accepts a UTF-8 Markdown file with an optional fenced `countersign-task`
JSON header. The rest of the Markdown describes the task. The browser form
generates this file; users do not need to write JSON.

## Browser fields

| Field | Content |
|---|---|
| Title | One line, up to 160 characters |
| Project roots | One to eight unique aliases with existing absolute directory paths; `~` is supported |
| Goal | Expected behavior and its purpose |
| Acceptance criteria | Observable conditions for a satisfactory result |

These fields are required. Optional fields: current behavior and errors, known
entry points, additional constraints, and deferred verification (one check per
line). Write task content in English; generated instructions and section labels
are English. The planner normally discovers related files and exact edits; no
implementation plan or exhaustive file list is needed.

Example goal: "Rebuild the API image without Docker layer cache for every local
stack start and suite run, locally and in CI." Example criterion: "Only the API
image bypasses cache; services reuse the fresh image from their current suite; a
failed build stops execution." See [`examples/live`](../examples/live) for complete
task files.

## Header

```countersign-task
{
  "roots": {"project": "~/src/my-project"},
  "verification": ["Run the scenario twice in the target environment and verify the expected result"],
  "read_only": false,
  "isolation": "in_place"
}
```

| Key | Meaning |
|---|---|
| `roots` | Alias to directory. Roots must not coincide or contain one another; relative paths resolve from the task file's directory |
| `verification` | Deferred runtime checks to report, not commands to execute |
| `read_only` | `true` for an answer-only task (the browser's **Answer only**) |
| `design` | `true` for a design discussion (the browser's **Design discussion**); implies `read_only` |
| `auto_approve` | `true` approves local commands, read access and the change limit of this run without asking (the browser's **Allow all actions**); SSH keeps its root-only approval |
| `isolation` | `in_place` (default) edits the roots; `worktree` edits new linked Git worktrees (the browser's **Isolated Git worktree**), see below |

Without `roots`, the CLI uses the repository that contains the task file (found
through `.git` without running Git); a task outside a repository needs explicit
roots. The browser always requires roots and rejects filesystem roots, overlap with
the run store, duplicate aliases and unknown request fields. Aliases use Latin
letters, digits, underscores and hyphens. The CLI does not apply the browser's form
validation to arbitrary Markdown, so fill in or remove all template placeholders.

## Worktree isolation

With `"isolation": "worktree"` every root must be the top level of a Git repository.
Before planning, the run creates one linked worktree per root from its current
`HEAD` on a new branch `countersign/<run>`, under `worktree_base` (default: a
`worktrees` folder beside the run store). Uncommitted changes in the source checkout
are not included. The whole run, including Continue, works in the worktrees; the
source checkout and its other branches may change meanwhile without stopping the
run. Changes stay uncommitted in the worktrees: the report lists each worktree and
branch, and you review, commit, merge and finally `git worktree remove` it yourself.
A browser follow-up continues in the same worktrees; Restart starts again from the
source checkouts in new worktrees.

## Execution boundaries

Models and timeouts belong in server-side settings. The workflow edits original
sources, preserves existing work, allows controlled Git operations and never rolls
back automatically. It runs built-in syntax checks, the operator's
[verification commands](deployment.md#verification-commands) and static review.
Other project tests, containers, deployments and CI run only when an agent requests
them through `LOCAL_REQUEST` or an SSH action and you approve; otherwise they remain
deferred. A
no-change result requires independent plan review and sufficient evidence.

An answer-only task rejects any implementation plan and never reaches the
implementer, even with an imported plan. The answer appears in the planner
conclusion and is independently reviewed.

Each submission creates a separate run. After a run stops, a new Goal starts another
complete planning pass with explicit prior evidence; it never messages an in-flight
model session. Follow-up goals inherit roots, entry points and constraints; the new
Goal takes precedence and prior findings are rechecked. Server-generated
`Conversation history` sections are reserved; do not add them to form fields. The
task file is saved as `.submissions/<id>/task.md` and snapshotted into the run's
`00-input/task.md`.
