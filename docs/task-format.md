# Task format and New task form

The CLI accepts a UTF-8 Markdown file with an optional fenced `taskrail-task`
JSON header. The rest of the Markdown describes the task. The browser form
generates this file; users do not need to write JSON.

## Markdown task files

After the header comes an optional `# Title` line, then either plain text, which is
the whole Goal, or these `##` sections, each at most once:

| Section | Field |
|---|---|
| `## Goal` | Required. Expected behavior and its purpose |
| `## Acceptance criteria` | Observable conditions for a satisfactory result |
| `## Current behavior` | Context: the problem and errors, if known |
| `## Known entry points` | Context: suggested files |
| `## Constraints` or `## Additional constraints` | Rules every task of a split keeps |
| `## Verification` | Deferred runtime checks, one per line; they join the header's `verification` |

The sections become the same typed fields the browser submits, so CLI tasks get the
same requirement labels, global constraints and sealed split children. Every
paragraph and top-level list item of Goal, Acceptance criteria and Constraints is a
requirement; a single line ending with `:` (such as `Requirements:`) or a lone
heading only introduces the blocks after it. Headings inside code fences are text.
Any other `#` or `##` heading, a repeated section, and text outside the sections
(once a section exists) are errors that name their line. See
[`examples/live`](../examples/live) for complete task files.

## Browser fields

| Field | Content |
|---|---|
| Projects | Required. One to eight existing absolute directories; `~` is supported. An empty name becomes the directory name (numbered on a clash) |
| Goal | Required. Expected behavior and its purpose |
| Acceptance criteria | Observable conditions for a satisfactory result; empty means the Goal itself, with verification limits reported |
| Mode | **Develop** (large work is split into tasks), **Answer only** or **Design discussion** |
| Title | Under **More details**; one line, up to 160 characters, default the Goal's first line |

**More details** also holds current behavior and errors, known entry points,
additional constraints, and deferred verification (one check per line). Write task content in English; generated instructions and section labels
are English. The planner normally discovers related files and exact edits; no
implementation plan or exhaustive file list is needed.

Example goal: "Rebuild the API image without Docker layer cache for every local
stack start and suite run, locally and in CI." Example criterion: "Only the API
image bypasses cache; services reuse the fresh image from their current suite; a
failed build stops execution." See [`examples/live`](../examples/live) for complete
task files.

The run's **Task** panel starts with a collapsed **Original task** card showing
the submitted goal, acceptance criteria, constraints and deferred checks as labeled
text. **Initial context** holds starting behavior and suggested files as historical
input, not current project state. The nested **Source file** retains the original
text, including generated metadata and workflow rules. **Requirements** is a
separate collapsed list immediately after the original task, under the `R<n>` labels
the agents use (the stored ID shows on hover). Each stage's collapsed **Requirement
coverage** and its plan criteria repeat the label and full text of each requirement. Expanding a panel
survives polling within the same run. These views do not change the saved task or
the agents' input.

## Header

```taskrail-task
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
| `decompose` | `true` always splits the Goal into task runs, even a small plan; see [delivery](task-controls.md#delivery-of-a-code-change) |
| `phase` | Server-generated for the runs of a delivery (`task`, `integration`, `validation`, `server`); do not set it by hand |
| `task_scope` | Required for server-generated `task` phases: exact reviewed file paths; child planning cannot widen them or create another split |
| `design` | `true` for a design discussion (the browser's **Design discussion**); implies `read_only` |
| `auto_approve` | `true` approves local commands, read access and the change limit of this run without asking (the browser's **Allow all actions**); SSH keeps its root-only approval |
| `isolation` | `auto` (default) isolates a code change whose roots are all Git repository top levels with a commit; `worktree` always edits new linked Git worktrees and commits each approved task there; `in_place` edits the roots (the browser's cleared **Isolated Git worktree**, `taskrail submit --in-place`), see below |
| `task_spec` | Generated typed input: version 1, literal named fields, a display integrity reference and optional child context/requirement lineage; do not edit only its Markdown display |
| `assigned_contract` | Generated child reference (`parent_run`, `task_id`); the workflow authenticates it against the sealed reviewed parent before skipping child planning |
| `check_specs` | Selected server recipe IDs and runtime criterion IDs; commands and approval policy remain server-owned |

Without `roots`, the CLI uses the repository that contains the task file (found
through `.git` without running Git); a task outside a repository needs explicit
roots. The browser always requires roots and rejects filesystem roots, overlap with
the run store, duplicate names and unknown request fields. Names use Latin
letters, digits, underscores and hyphens. The CLI does not apply the browser's form
validation to arbitrary Markdown, so fill in or remove all template placeholders.

The browser passes field boundaries directly to `task_spec`; Markdown headings in
user text cannot change those boundaries. Original field text and the complete
submitted file remain stored verbatim. Requirements retain stable content IDs and
source character ranges. A scoped child requirement retains its parent ID and exact
text; global constraints apply unchanged to every child. Task prompts contain user
fields once, without the JSON transport or copied server policy. Standalone restart drafts use
the typed fields directly; a task file of an older release that the Markdown reader
rejects is offered whole as the Goal. A split whose parent requirements lack typed
field provenance or a sealed reviewed plan cannot start children; restart the parent.
Authenticated typed children use a sealed `00-input/reviewed-task-spec.json` projection on first launch and
Continue; the original submission remains unchanged in `00-input/task.md`.
Continue resolves check IDs against the run's sealed recipe catalog, so removing
a recipe from current settings cannot replace or lose an
already approved check. A changed frozen catalog stops continuation.

Every planner turn has `plan.md` attached, so the planner edits it without reading it
again.
Unknown plan sections, unparsed ownership text and mismatched scope delimiters are
errors, with line numbers. Put `## Answer` last: its remaining Markdown is the answer.
Optional `## Check selections` lines have the form `recipe-id: R2, R4`; only advertised
recipes and runtime requirements are accepted. This selects existing server actions,
not model-authored commands. A write-before-read rejection for this exact plan file
gets bounded same-session feedback to read it; source writers are never retried by
this correction.

## Worktree isolation

A code change runs in worktrees by default: with `"isolation": "auto"` (or no
`isolation`) when every root is the top level of a Git repository with a commit and
not already on a `taskrail/` branch, as a task or follow-up of an isolated run is.
Answers, designs, delivery checks and other roots work in place. With
`"isolation": "worktree"` every root must be such a top level, otherwise the run
stops. Before planning, the run creates one linked worktree per root from its current
`HEAD` on a new branch `taskrail/<run>`, under `worktree_base` (default: a
`worktrees` folder beside the run store). Uncommitted changes in the source checkout
are not included. The whole run, including Continue, works in the worktrees; the
source checkout and its other branches may change meanwhile without stopping the
run. Clear **Isolated Git worktree** in the browser form, or pass
`taskrail submit --in-place`, to edit the roots themselves.

These `taskrail/` branches hold only the run's own work, so a task there is a unit of
change rather than a list of files:

- The planned files are the expected scope, not a limit. The implementer may change
  any other file of the roots, except Git metadata and protected files, when its task
  cannot be complete and valid without it; such a file gets its preimage from the
  branch's last commit, appears in the diff, is judged by the reviewer and is listed
  under **Changed beyond the plan** in the report. In place, the plan still limits the
  files.
- Each approved task becomes one commit on its branch: exactly the files the run
  changed, without hooks, with the implementer's summary as message and a
  `Taskrail-Run:` trailer. The report lists each commit; a failed commit is reported
  and never retried. A split's tasks therefore follow each other as commits, and the
  next task starts from the previous one.

Changes of a run that was not approved stay uncommitted in the worktree. You review
and merge each branch and finally `git worktree remove` it yourself. A browser
follow-up continues in the same worktrees; a standalone restart starts from the
source checkouts in new worktrees. Restarting a reviewed split child keeps the
parent's effective roots, including its existing worktrees.

## Execution boundaries

Models and timeouts belong in server-side settings. The workflow edits original
sources, preserves existing work, allows controlled Git operations and never rolls
back automatically. It runs built-in syntax checks, the operator's
[verification commands](deployment.md#verification-commands) and static review.
Agents run project tests and linters through `LOCAL_REQUEST`, without a decision in
the [local command sandbox](access.md#local-commands) where the host has one.
Commands outside it, containers, deployments and CI run only after your approval,
SSH and Jenkins through the executor; otherwise they remain deferred. A
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
`00-input/task.md`. History blocks never become requirements; a large history reaches
the prompt through the indexed `00-input/history.md` (see
[task controls](task-controls.md#conversation-context)).
