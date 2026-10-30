# Controlled Git access

All roles can inspect Git history, commits, diffs, branches, tags and working-tree
status. A declared root may be a subdirectory of a Git repository. Scope history
with `-- .` when the task concerns only that project. Original project files remain
in place; the executor does not create project copies.

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
- Implementer: additionally `add -- <files>`, `commit -m <message>`,
  `revert --no-edit <full hash>`, `cherry-pick --no-edit <full hash>`,
  `merge --ff-only <full hash>`, `fetch <remote>`,
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

Writes must affect only approved files. Staging pre-existing user edits is rejected.
Commit application requires a clean working tree. The index belongs to the run only
entry by entry and repository by repository: an `add` records the exact staged modes and blobs
it produced in its repository, and a later `add` or `commit` there proceeds only
while every staged entry is one of those blobs. Changes the user staged, in that or
any other repository, and an entry changed after the run staged it, are rejected even
inside approved files. A commit or other history write ends that ownership. Merge
commits are not yet supported for revert/cherry-pick. A rejected request returns
feedback for further analysis; the task need not stop unless the operation is
mandatory and unresolved.

After a successful controlled commit, later staging uses that verified committed
content while original preimages stay immutable. Receipts pin HEAD and validate
the complete changed-path set, staged content and executable modes. Concurrent index
or HEAD changes, failed receipt reads and unexpected byte normalization produce an
unknown outcome rather than adopting another writer's work; inspect before restarting.

The same write is not repeated: an identical request is rejected while its earlier
outcome is unknown, and other writes are never repeated. An `add` or `commit` that
repeats an earlier one with a known outcome runs only when what it acts on changed:
the files to stage after further edits, or the staged content to commit. A failed or
interrupted write is never automatically replayed or rolled back. Conflicts remain
for inspection. An unknown outcome blocks continuation pending operator
reconciliation; start a new task after inspecting the repository.

Hooks, external diffs, text conversion, process filters, custom merge drivers, automatic signatures,
credential helpers and interactive credential prompts are disabled.
Signature verification helpers are disabled for reads. Pretty formats accept built-in
names or literal formats; configured aliases and `%G` signature directives are rejected.
Git must be installed on the server PATH. Commits require a configured user name/email.
SSH authentication must already work noninteractively with a known host key.
Each Git subprocess has a 60-second timeout and a 4 MiB output limit per stream;
exhaustion is explicit, never silently truncated. Normal pushes are explicit, non-forced branch pushes; fetch uses explicit,
non-forced remote-tracking refspecs. No server-side hooks or remote state changes
are claimed to have been tested by local executor tests.

## Automatic task commits

After independent approval, an owned isolated task stages and commits through the
same controlled executor. Ownership comes from the run's sealed worktree record
and its current repository, path and branch identity; a `taskrail/` branch name
alone grants nothing. Source files must still match the reviewed snapshot.
Unrelated staged entries and pre-existing user edits are rejected before staging.
Filters and hooks stay disabled, and a successful receipt verifies the committed
paths, bytes, executable modes and HEAD before the run can finish successfully.

Each changed repository has its own commit receipt. Automatic finalization adds
at most one new commit per root; explicit task-requested Git operations may already
have created commits, which are verified and reused when applicable. Finalization records a
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
no email is configured; explicit model Git requests still require configuration.

## Artifacts and updates

- `git-execution.json`: exact requests, effective arguments, statuses and output paths.
- `00-input/git/<stage>-<sequence>.txt`: full command output, readable but not editable by agents.
- `checkpoint.json`: source/Git fingerprints after controlled execution.

Uncontrolled metadata changes stop the workflow, and nothing is rolled back
automatically. An interrupted action journal remains authoritative; a new launch
cannot silently replay the action. Running tasks keep their frozen instructions. A
task that forbids Git also forbids history inspection; the server never rewrites the
user's task text.
