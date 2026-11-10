# Controlled Git access

Planning, implementation and review can inspect Git history, commits, diffs, branches,
tags and working-tree status. Each declared root must be a Git repository top level with an existing commit.
Standalone tasks use linked worktrees; child tasks use their parent branch. Scope
history with `-- <project>` when only a subdirectory is relevant. The original checkout
remains unchanged.

The model submits one strict `GIT_REQUEST` object instead of a final result:

```json
{"schema_version":1,"status":"GIT_REQUEST","root":"/absolute/project/root","argv":["log","-3","--format=fuller","--stat","--","."],"reason":"Inspect recent project changes"}
```

The server executes Git without a shell, records exit status and full output, then
returns output to the same opencode session inside the same workflow stage. The UI
shows a Git tool call and its result. Short output is attached directly; long output
is clipped with a path for targeted reads. Snapshots retain full output for audit
and exact evidence citations; they do not create workflow stages. A request is not proof of execution.

For read-only Git commands, the dispatcher also accepts one unambiguous JSON
object surrounded by prose or a Markdown fence. It never repairs arguments or
chooses among multiple objects. Requests that can change state must be the entire
response. A request with unknown or missing fields, a wrong version or an empty reason
runs nothing; the same session is told what to fix. Root and command validation still
apply. Read requests are routed to the executor before final-result validation.

## Permissions

- Planner/reviewer: read operations only (`log`, `show`, `diff`, `status`, `reflog`,
  `rev-parse`, `ls-files`, `ls-tree`, `blame`, `describe`, `merge-base`, `cat-file`,
  branch/tag listing, `remote -v`).
- Implementer on the task branch: `restore --worktree -- <explicit files>`, `fetch <remote>`,
  `push <remote> HEAD:refs/heads/<branch>`, when needed by the task. A push waits for
  your personal decision in the UI (or `taskrail decide`); **Allow all actions** does
  not cover it.
- Always forbidden: hard reset, clean, history rewriting, amend, rebase and forced
  pushes, including force-with-lease and `+refspec`. Direct metadata writes and
  model shell execution remain disabled.

The executor accepts a bounded command/option grammar. Unsupported syntax returns
an explicit rejection; it never falls back to shell execution. There is no blanket
Git deny. Additional Git operations require an explicit reviewed parser and scope
check, not a prompt-only permission change.

On a task branch, staging and committing belong to [server finalization](#automatic-task-commits).
Before it writes, the executor checks the exact staged modes and blobs against its
record of the index. Foreign staging and concurrent changes require inspection.
If a Git mutation has an unknown outcome, new mutations wait for reconciliation.
Read-only Git diagnostics remain available to the agent.

An agent may recover an interrupted project-file edit with
`restore --worktree -- <explicit files>` after inspecting the current diff. Restore
uses the current index, leaves staging and commits unchanged, and only accepts tracked,
unconflicted files in the approved scope. Their original content must match the
trusted committed baseline; selected staged entries must belong to this run. Unrelated
staging is preserved. Pre-existing edits, foreign staged entries, untracked files,
directories, path patterns, symlinks and other restore options are rejected with
feedback. The agent can repair such files directly while retaining user changes.
No automatic rollback or blanket reset is performed.

Hooks, external diffs, text conversion, process filters, custom merge drivers, automatic signatures,
credential helpers and interactive credential prompts are disabled.
Signature verification helpers are disabled for reads. Pretty formats accept built-in
names or literal formats; configured aliases and `%G` signature directives are rejected.
Git must be installed on the service PATH.
SSH authentication must already work noninteractively with a known host key.
Agent-requested Git commands have a 60-second timeout and a 4 MiB output limit per stream;
exhaustion is explicit, never silently truncated. Normal pushes are explicit, non-forced branch pushes; fetch uses explicit,
non-forced remote-tracking refspecs. No server-side hooks or remote state changes
are claimed to have been tested by local executor tests.

## Automatic task commits

After independent approval, an owned isolated task stages and commits through the
same controlled executor. Ownership comes from the run's sealed worktree record
and its current repository, path and branch identity; a `taskrail/` branch name
alone grants nothing. Source files must still match the reviewed snapshot.
For a Follow-up, the reviewed task's `Files` list selects which inherited changes
belong to the task. The reviewer sees their full working versions against HEAD.
Only after approval may finalization stage those versions and commit the exact
reviewed paths, leaving every other staged or unstaged change in place.
Ordinary tasks reject pre-existing user edits and unrelated staging.
Filters and hooks stay disabled, and a successful receipt verifies the committed
paths, bytes, executable modes and HEAD before the run can finish successfully.

Each changed repository has its own commit receipt. Automatic finalization adds
at most one new commit per root. The writer submits the proposed message and leaves
staging, committing and changes to HEAD for finalization after review. Finalization records a
pending outcome before writing. A failed commit leaves the run `COMMIT_FAILED`
and stops delivery; a successful commit in an earlier root remains recorded.
Neither changes nor commits are rolled back. An interrupted or unverified write
remains unknown in the Git journal and prevents a split retry from bypassing it.
An explicit restart after a known partial failure inherits authenticated receipts:
it verifies and reuses already committed roots and unchanged owned index entries.
It never repeats an uncertain write. Inspect and reconcile an unknown outcome
before starting new work. An isolated task
with no remaining diff does not create an empty commit. Automatic commits use the
configured Git identity, with `Taskrail <taskrail@localhost>` as the fallback when
no email is configured.

## Artifacts and updates

- `git-execution.json`: exact requests, effective arguments, statuses and output paths.
- `00-input/git/<stage>-<sequence>.txt`: full command output, readable but not editable by agents.
- `checkpoint.json`: source/Git fingerprints after controlled execution.

Uncontrolled metadata changes stop the workflow, and nothing is rolled back
automatically. An interrupted action journal remains authoritative; a new launch
cannot silently replay the action. Running tasks keep their frozen instructions. A
task that forbids Git also forbids history inspection; the server never rewrites the
user's task text.

On an owned task branch, the writer may adopt additional safe project files.
Before each Git request the server refreshes the exact changed paths and their
preimages. Finalization can commit those reviewed paths together. Inherited Follow-up
changes require explicit selection in the reviewed task.
Git verifies index ownership before each write.
