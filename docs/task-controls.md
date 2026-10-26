# Task controls and conversation turns

## State and actions

| Action | Required state | Result |
|---|---|---|
| Restart from scratch (standalone run) | No active run on its projects | Open the prefilled task form; submit explicitly to create a new run |
| Restart reviewed task (split child) | Latest attempt of the next unfinished task; no active writer | Start a linked attempt from the approved parent plan, directly at implementation; preserve previous edits and original preimages |
| Restart this phase (integration review, Jenkins validation, server checks) | Latest stopped attempt of the phase | Start the phase again under the same delivery; the earlier run stays one of its attempts |
| Stop task | Running | Write a stop request; the worker cleans up opencode and saves an interruption checkpoint |
| Continue with extra budget | Eligible checkpoint; explicit confirmation | Add two attempts and one attempt timeout to the interrupted stage; retain consumption |
| Continue interrupted run | Eligible checkpoint and unchanged source | Append new attempts to the same run, starting at the interrupted stage; a stage that reported **Blocked** can continue too, with your note answering its question; an interrupted or blocked implementer first inspects its existing edits |
| Send a follow-up Goal | Previous standalone run stopped, no active run on its projects | Snapshot prior public evidence and start a new run from planning; a task or phase run has no follow-up, use Continue with a note or a follow-up of its parent |
| Answer only | New or follow-up submission | Research and independent review, no implementation; the reviewed answer opens the report and is the `answer` of `countersign status` |
| Design discussion | New or follow-up submission | Like Answer only, but the reviewed summary is a design document, saved as `design.md`; follow-ups refine it, a **Develop** follow-up implements it |
| Confirm changes | A finished code change, after integration review for a split and any Jenkins validation | Accept the change; server checks, if any, start only now |
| Mark as done / Move back from Done | Stopped run | Move the run to the Done group, or return it to its computed group; nothing else changes |
| Delete from history | Stopped/completed run | Move run and launcher artifacts to local trash; leave source files untouched |

Each run page shows its mode (**Develop**, **Answer only** or **Design discussion**;
older forced splits show **Split into tasks**); the run list shows the mode when it is
not Develop.

The run list groups runs by what they need:

| Group | Runs |
|---|---|
| Running | Starting or running, not waiting for you |
| Needs you | A pending UI decision, an SSH or Jenkins ticket waiting for root approval, or a stop without a successful result (errors, budgets, interruptions); highlighted in yellow |
| Ready for review | A finished change waiting for your confirmation |
| Done | Confirmed with its server checks finished, finished without changes, or marked done; collapsed until opened or searched |

## Delivery of a code change

Every **Develop** task goes through the same steps:

1. **Planning.** The planner chooses one atomic task (`single`) or several (`split`).
   Each task owns a deliverable, exact files, requirements or scoped parts, acceptance
   results, checks, dependencies and the line ranges its implementer reads first. It
   must fit one implementation session without compaction. Tasks run one after another
   in plan order; a later task sees the earlier changes. Plan review checks
   completeness, self-containment and ordering.
2. **Implementation and review.** A single task runs here. A split finishes planning
   as **Tasks ready**; the service starts child runs in dependency order, using the
   same roots or worktrees. A child starts directly at implementation after the server
   authenticates the approved parent plan, criteria, file scope and prerequisite
   source/Git snapshots; independent result review still follows. A child is never
   planned again: it cannot split or expand its parent's reviewed file scope. A contract that cannot be met
   reports the required parent replanning instead of launching nested tasks.
3. **Integration review for a split.** A separate read-only run checks the original
   goal and every acceptance criterion against the combined source, including
   interactions between tasks. The server prepares its scope, writes the combined diff
   of all task runs against the files before the split to its `changes.diff`, lists the
   files each task changed and starts one independent reviewer, preceded by configured
   local checks when present. Findings end the review as **Changes requested**; there
   is no writer to repair them, so the review is not repeated automatically.
   Child success reports and manual done marks cannot bypass this phase. It runs
   even without an SSH/Jenkins executor and must finish `NO_CHANGES_REQUIRED`.
4. **Jenkins validation.** Planned `Jenkins check:` entries run when Jenkins is
   configured. Starting each build requires root approval.
5. **Your confirmation.** **Confirm changes** accepts the result. For a split, the
   source and Git state must still match the integration review's checkpoint.
6. **Server checks.** Planned `Server check:` entries and deferred runtime checks
   run only after confirmation, through the isolated executor and root approval.
   Before confirmation, SSH requests may only inspect ([SSH executor](ssh-executor.md)).

The run page shows these steps in a **Delivery** panel as one graph: the tasks of a
split in columns by their dependencies, then integration review, Jenkins validation,
your confirmation and server checks. Each node shows its status and, after a retry,
how many earlier attempts it has. Select a node to work with its run inside the same
card: its stages, decision requests, actions, diff and report; a run that waits for
your decision is shown without a click. Earlier attempts collapse into one line
(`2 earlier attempts · #1 Invalid result · #2 Tool error`) that expands to open any
of them. The address `#parent/child` opens a node directly. The next task starts automatically after each successful
one (**Start the next task automatically after each successful one** is on); it stops
at the first task that does not finish successfully, and before a task marked **Pause
before this task**, for example when you want to review the code before a task that
checks it on a server. **Start S-n** starts the next task by hand; a task whose run
failed can be started again with **Start S-n again**. The new attempt continues from
the failed attempt's edits: its implementer is told the earlier outcome, review findings
and failed checks, and its diff compares against the original files. Every run started
for a task is recorded as an attempt, and the server checks the chain of attempts
before reusing the reviewed contract. Files or Git state changed outside the split's
tasks (by you, your IDE or another tool) never stop a task. The task gets their list
first: its implementer reads them, keeps an assigned change that is already there,
changes them as its task requires and keeps edits unrelated to it. The task's report
and card name them under **Changed outside this task**, and the integration review
sees them for each task, because the task's diff may include those edits. Edits made
while a stage of a task is running still stop that stage.
Marking a task's run done counts it as finished for scheduling, but reusing an approved
child contract requires actual accepted prerequisite results; a done mark cannot supply
that proof.
Each child gets its complete current contract and a bounded index of its
prerequisites and an immutable `00-input/parent-task.md` containing the complete
parent input, reviewed task contracts, checks, notes and recorded outcomes. The
artifact manifest grants read access; parent deletion does not remove this context.
Required acceptance text is never replaced by a truncated summary. An oversized
submission fails visibly and pauses auto-continue instead of looping silently.
**Allow all actions** on the parent applies to subsequently started children and checks
unless revoked. Unconfigured Jenkins/SSH phases are shown as skipped; integration
review is never skipped. **Repeat integration review** starts a new read-only review
when the earlier one stopped or its evidence is stale; it also invalidates later
validation and confirmation. Earlier phase links remain in the parent's history.

A task or check run is linked to its parent before its worker starts, and every change
of the parent's record (links, Pause, auto-continue, your confirmation) is serialized,
so none is lost to a concurrent one. If the application stops after linking a run but
before starting its worker, the next start marks that launch `LAUNCH_ERROR`; nothing
starts it again automatically, and **Start S-n again** starts a new run.

The run list puts a delivery under Running while code, integration review, validation or server checks run,
Needs you when a task, a check or an approval waits for you or failed, Ready for review
while it waits for your confirmation, and Done when it is confirmed and its server
checks finished. A split shows its progress (`Tasks 1/3`). Task and phase runs are not
listed separately: they open in their parent's card, and searching for their run ID
finds the parent. A task header with
`"decompose": true` requests child execution even for one task; children cannot inherit it.

A done mark belongs to the outcome it was given for: if a continuation ends with a
different result, the run leaves Done again.

Stop is cooperative. The worker checks requests at stage boundaries and while
waiting for opencode. Permission preflight, filesystem scans and short built-in checks
may finish before the request is observed. The UI shows the pending stop state.
No stored PID is signalled, so a reused PID cannot affect another process. The
existing process-group cleanup handles the opencode process and its children. Closing
the web page does not stop the worker. Stopping the managed application service
also requests this checkpoint-preserving interruption for its owned worker.

Continue is also offered after `INVALID_RESULT` and `TOOL_ERROR`, for example when
a writer finished its edits but returned an unusable response, or a required program
was missing. The optional note under the actions (CLI: `countersign resume RUN
--note TEXT`) is passed verbatim to the continued stage as `operator_note`, for
example "python3 is installed now". The task, approved scope and policy still apply;
an interrupted or failed writer inspects current files before editing again.

When an agent requests a local program that is not installed, the approval card says
so instead of rejecting the request. Install the program, then **Allow** the same
command, or **Deny**.

Resume retains frozen task/agent snapshots, approved scope and original preimages.
A run frozen by a release with other response schemas, or a child without a sealed
reviewed parent, stays viewable but cannot continue: Restart it (or its parent). If source or Git metadata changed after
the checkpoint, continuation refuses to
proceed. For a split child, use **Restart reviewed task**: the new attempt starts from
the current files and names the files changed outside the split. Replan the parent
when its scope or requirements changed. Standalone restart and follow-up establish a
fresh baseline; none of these actions revert earlier changes.

A child restart uses the parent's sealed plan, typed requirements, effective roots
and file scope. The new attempt is linked before its worker starts; completed,
superseded or running child attempts cannot be retried this way. The API restart
action has the same behavior; submitting a detached restart draft or a follow-up for a
task or phase run is rejected. **Restart this phase** starts a delivery phase again
under the same parent, so the parent never loses the link to its current phase run. An already detached run is not automatically reattached: stop it and
recover through the original parent, inspecting its changes before accepting files.

## Conversation context

Each follow-up has a separate run ID and task file. The task contains the latest
Goal and a snapshot of prior task text, goals, public conclusions, validated stage
results and diffs. History is reference data; prior goals do not override the latest
Goal. Current source must be read again. Earlier tool logs and hidden reasoning
are not copied into the new prompt. The interface displays the earlier public
messages, then the new workflow stages.

History is flattened across turns and limited to 256 KB. An oversized history
produces a visible error asking for a new task with selected context. No history is
silently discarded. `00-input/task.md` always keeps the complete history. When the
history part is larger than 24,000 bytes, stage prompts show the current task, the
latest earlier turn's goal and summary (each clipped to 2,000 characters, marked) and
the path of `00-input/history.md`. That file starts with an index of the turns and
the line ranges of their goal, summary, task, conclusions and diff, so the model reads
only the sections it needs. Smaller histories stay inline unchanged. Usage
monitoring applies to the selected run; each new turn starts a fresh configured
budget, unlike checkpoint continuation.

For a question, choose the **Answer only** mode. This sets server-generated `read_only`
metadata as well as instructions. Nonempty steps or proposed change paths are
rejected by plan validation, and a separate transition guard blocks implementation.
A successful reviewed answer finishes as `NO_CHANGES_REQUIRED` with its conclusion.
Changing back to **Develop** on the next turn removes the answer-only constraint.

## Deletion

The UI asks for confirmation and moves artifacts to `<runs>/.trash/<run-id>/`:
`run/` holds stage history, while sibling directories hold launcher records. Source
roots are never moved or edited. There is no automatic trash purge. To restore,
stop all workflows and manually move `run/` back to `<runs>/<run-id>` and the
launcher folders back under `.submissions/`, without replacing existing paths.

Deletion holds the run's lock, so its worker cannot start meanwhile. Active runs, path
traversal, symlinked runs and symlinked trash/submission storage are rejected.
A child turn retains its snapshotted context even if its ancestor is removed.

## Local API

Same-origin and CSRF-token checks apply to every mutation (`POST /api/tasks`,
`/api/actions`, `/api/decision`). `/api/actions` accepts
`{"id":"run-id","action":"restart|resume|resume_budget|stop|delete"}`, and a
continuation may add `"note"`; `resume_budget`
is **Continue with extra budget**, and restart returns a `draft` without launching
anything. `/api/tasks` accepts the task fields plus the booleans `read_only`,
`worktree`, `design` and `auto_approve`, and optionally `parent_run` with `submission_mode`
`restart`, `followup`, `answer` or `design`; without a parent the mode is `new`. `/api/decision` answers one pending approval ticket with
`allow`, `deny` or `alternative`; an `allow` may add `"allow_all": true`. Commands and settings stay server-owned. Reads use
`GET /api/session`, `/api/runs`, `/api/run` and `/api/analytics`. `/api/actions` also
accepts `epic_next`, `epic_auto_on`, `epic_auto_off`, `confirm`, `integration_review`,
`done`, `reopen`, `revoke_auto_approve`, and with a `"task"` field `epic_pause` and
`epic_unpause`.

## Automation from the CLI

When the browser cannot be used, for example a chat bot on the server, the CLI starts
and controls runs through the same launcher, validation and run store. Each command
prints one JSON object and returns at once; the task runs in a detached worker.

```sh
countersign submit --root shop=/srv/shop --goal @goal.md --mode answer --allow-all
countersign status RUN                       # status, answer, worker activity, approval, delivery step
countersign decide RUN alternative --text "Use tox instead"
countersign action RUN resume --note "python3 is installed now"
countersign submit --json payload.json       # the fields of POST /api/tasks
```

`--mode` is `develop` (the default), `answer`, `design` or `split`; `--followup RUN` and `--restart RUN`
continue a conversation; a text option may name a file as `@FILE`. `action` accepts the
`/api/actions` actions. For a standalone run, `action RUN restart` prints the saved
`draft`; submit the edited fields with `parent_run` and `submission_mode: "restart"`
in the JSON payload. For a split child, `action CHILD_RUN restart` launches a new
linked attempt of the same reviewed task directly, and `action PHASE_RUN restart` runs a
delivery phase again under its parent; `submit --restart` or `--followup` naming a task
or phase run is rejected because a detached run would lose its parent.
Automatic steps of a split (the next task, integration review,
Jenkins validation, server checks after confirmation) need the managed service.

## Decisions and continuation

A denied read/search opens **Your decision required**. Choose **Allow**,
**Deny and continue**, or **Send alternative**. Allow can authorize exact reads
inside declared roots; it cannot widen roots or grant source edits. Denial is
feedback, not automatically a failed task. If the denied evidence is mandatory and
no permitted alternative exists, the agent must still report the unresolved gap.

Local commands use the same single-use decision flow. Waiting has no deadline and
does not consume the stage timeout. The timer resumes after the decision; command
execution does consume time. SSH tickets retain root-only approval and their own
execution timeout. Stop interrupts waiting. A stale browser decision cannot approve
a different request.

**Allow all actions** skips these cards for one run. Tick it in the task form to
apply it from the start (restarts and follow-ups keep the choice), or tick **Allow all
further actions in this run** on a card and choose Allow. Local commands, read access
and the change limit are then approved without asking, and each automatic approval is
recorded in the same ledger with `"automatic": true`. The run shows an **All actions
allowed** badge and a **Stop allowing all actions** button, which takes effect before
the next decision and also on Continue. A choice made on a card lasts until the worker
exits; Continue asks again unless the task form enabled it and it was not stopped.
Read-only requests never ask ([access](access.md#local-approval)). Pushes and inline
shell or Python code from agents (`bash -c`, `python -c`) always ask. SSH tickets and
Jenkins builds always keep root-only approval.

Git and approved local actions resume the same opencode session inside one stage. A
missing/changed session ID stops continuation rather than starting fresh research.
Continue from a saved checkpoint still checks source and Git integrity; it never
blindly repeats an interrupted write. See [access](access.md).

Local commands are recorded before execution in `local-actions.json`, including exact
argv, approval, source snapshot and an environment fingerprint. An interrupted or
uncertain action remains `UNKNOWN`; rephrasing its reason or continuing the run cannot
execute it again. Intermediate requests are bounded per stage: 64 total and at most
three identical local/Git requests against unchanged sources. `NO_PROGRESS` stops
before another request runs; continuation retains these counters.

## Exhausted allowances

After an interrupted or budget-limited stage, use **Continue with extra budget**
when the normal allowance has been exhausted. The server first checks the saved
checkpoint and source integrity. The grant is recorded in `budgets.json`; it applies
only to that stage and never clears consumed tokens or calls. The run-wide token
cap stays unchanged. If that cap stopped the run, deliberately increase it in
settings before continuing. Ordinary Continue grants no additional allowance.

A genuine blocked task or unsafe checkpoint is not converted into an automatic retry.
A terminal task can be deleted even if an old launcher record still says RUNNING;
the run and project locks and current worker checks continue to protect active tasks.
Deleting history moves artifacts to local trash and never changes project files.

CLI equivalent:

```sh
countersign resume /absolute/path/to/run --extend-budget
```
