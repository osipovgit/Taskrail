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
same requirement labels, global constraints and sealed split children. A separate
task-understanding stage extracts obligations from the full narrative, including
requests embedded in background fields. Paragraphs and bullets do not define requirement
boundaries. Background remains available in the unchanged original text. The server
validates exact quoted source fragments and assigns stable IDs; see
[the interpretation contract](contracts.md). Headings inside code fences are text.
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
additional constraints, and deferred verification (one check per line). Task input may
use the user's language; generated explanations, instructions and section labels are
English. The planner discovers likely change files and the implementer determines the edits; no
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
text, including generated metadata. Server workflow rules are supplied in stage
requests, never appended to task fields or listed as requirements. **Requirements** is a
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
  "read_only": false
}
```

| Key | Meaning |
|---|---|
| `roots` | Alias to directory. Roots must not coincide or contain one another; relative paths resolve from the task file's directory |
| `verification` | Deferred runtime checks to report, not commands to execute |
| `read_only` | `true` for an answer-only task (the browser's **Answer only**) |
| `decompose` | `true` always splits the Goal into task runs, even a small plan; see [delivery](task-controls.md#delivery-of-a-code-change) |
| `phase` | Server-generated for delivery runs (`task`, `integration`, `correction`, `validation`, `server`); do not set it by hand |
| `task_scope` | Required for server-generated `task` phases: exact reviewed file paths; child planning cannot widen them or create another split |
| `design` | `true` for a design discussion (the browser's **Design discussion**); implies `read_only` |
| `auto_approve` | `true` approves local command decisions for this run (the browser's **Allow all actions**); SSH keeps its root-only approval |
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
the typed fields directly. Parent requirements and reviewed plans must have valid
provenance and seals before a split can start children.
Authenticated typed children use a sealed `00-input/reviewed-task-spec.json` projection on first launch and
Continue; the original submission remains unchanged in `00-input/task.md`.
Continue resolves check IDs against the run's sealed recipe catalog, so removing
a recipe from current settings cannot replace or lose an
already approved check. A changed frozen catalog stops continuation.

Every planner turn has `plan.md` attached, so the planner edits it without reading it
again.
Unknown plan sections, unparsed ownership text and mismatched scope delimiters are
errors, with line numbers. Inside a task, a line that is no plan key (an invented
`Facts:` key or prose) is kept as part of its Notes; at the top of the plan it is named
as not a plan key. `Files:` names exact paths; a pattern, directory or sentence there
is reported with its line and entry. A `## T<n>: After the change` heading opens the
after-change section, and a `None` line there lists no check. Put `## Answer` last: its remaining Markdown is the answer.
A task may list `Not ToDo:` bullets: later work its implementer might be tempted to do.
It is a hint, never a validation rule. The child's **Not ToDo** block combines them with
every later task's title, results and files: work to leave to those tasks unless this
task cannot work without it, in which case the implementer does only the minimum and
names it in its summary. A necessary additional file is allowed on an owned task branch.
`Required checks:` lists exact local recipe IDs, one per bullet, or `none`. Selected
gates run before that task can finish and again on the combined integration result.
Unknown recipes, remote recipes and model-authored commands are rejected. `Verify`
remains human-readable verification guidance and never authorizes arbitrary commands.
Optional `## Check selections` lines bind an advertised recipe to runtime criteria
as `recipe-id: R2, R4`. For ordinary local commands in `Verify`, the executor
checks each request when the agent submits it. See [verification](checks.md).

Native tool errors return to the agent in the same session. It can inspect the
current file and correct an edit. The server validates the saved result and its evidence
after the turn. See [recovery and tool errors](contracts.md).

## Worktree isolation

Source evidence uses the current effective roots, including isolated worktrees.
Repository documentation inside those roots is eligible after an observed read;
the original checkout, an adjacent worktree or a README above a nested root is not
implicitly authorized. An out-of-scope citation reports the exact effective roots.
Each stage receives the recorded source-checkout to worktree mapping. Exact source
paths in a plan's `Files` and future `Read` hints are translated to the corresponding
effective root before validation. Evidence, observed reads, executor requests and
the original task/plan text are never rewritten; the accepted result records the
effective targets. Unknown checkouts, noncanonical paths and symlinks do not gain
access through this mapping, and normal target and scope checks still apply.

Every standalone task, including answers and designs, requires repository top-level
roots with an existing commit. Taskrail validates all roots before creating one linked
worktree per root on the server-named branch `taskrail/<run>`. There is no in-place mode. The installer removes the retired `isolation` setting
with a private backup; task headers containing it are rejected.
The branches appear immediately in the shared repositories; original checkouts never
switch branches. Storage is `worktree_base` (default `~/.local/share/taskrail-worktrees`,
outside application state). Authenticated split children and delivery phases reuse the
parent's worktrees. Follow-up ownership and locks remain valid if the old parent
checkout is moved or removed. Continue uses the same branch; Restart creates a new branch from
the original checkout. A task without edits leaves an empty branch for the operator to
remove; Taskrail never merges it or removes it automatically.

A Follow-up creates a new branch from the previous task's HEAD and copies its staged,
unstaged and nonignored untracked changes, including deletions, binary files, executable
modes and symlinks. The previous checkout and index remain unchanged. A capture failure
or concurrent source change stops initialization instead of silently dropping files.
For a Follow-up or one of its split tasks, listing a carried file under the task’s
`Files` selects its current working version, including any further implementation edits.
The server captures the file at the task’s starting HEAD as its preimage and gives the
result reviewer its full diff, including binary patches and executable-bit changes.
Once the reviewer approves, the server commits the selected versions alongside ordinary
task changes. Other carried files keep their index and working versions. A file listed
only under `Read` stays available for inspection.

For an ordinary new task, the branch starts at HEAD; before
planning, Taskrail records the original checkout's Git status in
`00-input/original/status.jsonl`. Each row names the path, the index/worktree
status (Git XY), and available versions relative to that snapshot directory.
Staged content is under `index` and unstaged or new content under `working`.
A deletion has no file for the deleted side. Protected paths, conflicts,
links, nonregular files and capture failures are identified explicitly. Copies are
limited to 8 MiB per version and 128 MiB per run.

When the task requests existing edits, review the applicable rows against the
isolated files. Port selected hunks with normal edits, or copy a selected
version using `LOCAL_REQUEST` after checking for earlier changes at the
destination. Preserve executable mode where relevant. Verify the resulting
diff and use the normal reviewed commit flow. The local sandbox exposes the
snapshot read-only. Split tasks inherit the launch snapshot. The whole run, including Continue, works in the worktrees; the
source checkout and its other branches may change meanwhile without stopping the
run.

The server seals the effective roots, source-to-worktree mapping and permission
base in `00-input/execution-context.json`. A split child inherits them only after
the reviewed parent, assignment and source lineage pass authentication. Delivery
checks also require the parent's exact phase link. Continue restores the run's
own sealed context; it does not depend on the parent still being present.
A missing provenance seal is invalid. A branch name alone never grants isolated-task
permissions or automatic commits.

An authenticated isolated task is a unit of change rather than a list of files:

- The planned files are the expected scope, not a limit. The implementer may change
  any other file of the roots, except Git metadata and protected files, when its task
  cannot be complete and valid without it; such a file gets its preimage from the
  branch's last commit, appears in the diff, is judged by the reviewer and is listed
  under **Changed beyond the plan** in the report.
- Automatic finalization creates at most one new commit per changed repository,
  with the implementer's summary and a `Taskrail-Run:` trailer. The controlled
  executor verifies the reviewed content and refuses unrelated staged or
  pre-existing user edits. The report lists the verified commits. A failure ends
  as `COMMIT_FAILED`, keeps any earlier successful root receipts and stops the
  split; an uncertain write cannot be replayed by restarting its child. See
  [automatic commits](git-access.md#automatic-task-commits). The next task starts
  only after successful finalization.

Review and merge each task branch when ready, then remove its linked worktree with
`git worktree remove`. A Follow-up starts in new worktrees with the prior result.
A standalone restart starts from the original source checkouts in new worktrees. Restarting a reviewed split child keeps the
parent's effective roots, including its existing worktrees.

## Execution boundaries

Models and timeouts belong in server-side settings. The workflow edits isolated
sources, preserves existing work, allows controlled Git operations and never rolls
back automatically. It runs built-in syntax checks, the operator's
[verification commands](deployment.md#verification-commands) and static review.
Agents run project tests and linters through `LOCAL_REQUEST`, without a decision in
the [local command sandbox](access.md#local-commands) where the host has one.
Host execution follows `host_commands`. Remote operations use the
[SSH and Jenkins executor](ssh-executor.md) and its approval rules. A
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
