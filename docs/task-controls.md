# Task controls and conversation turns

## State and actions

| Action | Required state | Result |
|---|---|---|
| Restart from scratch | No active run on its projects | Open the prefilled task form; submit explicitly to create a new run |
| Stop task | Running | Write a stop request; the worker cleans up opencode and saves an interruption checkpoint |
| Continue with extra budget | Eligible checkpoint; explicit confirmation | Add two attempts and one attempt timeout to the interrupted stage; retain consumption |
| Continue interrupted run | Eligible checkpoint and unchanged source | Append new attempts to the same run, starting at the interrupted stage; a stage that reported **Blocked** can continue too, with your note answering its question; an interrupted or blocked implementer first inspects its existing edits |
| Send a follow-up Goal | Previous run stopped, no active run on its projects | Snapshot prior public evidence and start a new run from planning |
| Answer only | New or follow-up submission | Research and independent review, no implementation |
| Design discussion | New or follow-up submission | Like Answer only, but the reviewed summary is a design document, saved as `design.md`; follow-ups refine it, a **Change code** follow-up implements it |
| Confirm changes | A finished code change, after any Jenkins validation | Accept the change; server checks, if any, start only now |
| Mark as done / Move back from Done | Stopped run | Move the run to the Done group, or return it to its computed group; nothing else changes |
| Delete from history | Stopped/completed run | Move run and launcher artifacts to local trash; leave source files untouched |

Each run page shows its mode (**Change code**, **Answer only** or **Design discussion**;
older forced splits show **Split into tasks**); the run list shows the mode when it is
not Change code.

The run list groups runs by what they need:

| Group | Runs |
|---|---|
| Running | Starting or running, not waiting for you |
| Needs you | A pending UI decision, an SSH or Jenkins ticket waiting for root approval, or a stop without a successful result (errors, budgets, interruptions); highlighted in yellow |
| Ready for review | A finished change waiting for your confirmation |
| Done | Confirmed with its server checks finished, finished without changes, or marked done; collapsed until opened or searched |

## Delivery of a code change

Every **Change code** task goes through the same steps:

1. **Planning is decomposition.** The planner plans the Goal as tasks: a small goal is
   one task, larger work several (at most 8), each with its files, covered requirements,
   dependencies and acceptance checks. Plan review checks the plan.
2. **Implementation and review.** When all tasks together change at most as many
   files as one review allows (`max_change_files`, 15 by default), this run implements
   and reviews them. Otherwise the run stops as **Tasks ready** and each task runs as
   its own run with its own planning, implementation and review rounds, one after
   another in the same projects (the same worktrees if the task was isolated).
3. **Jenkins validation.** When the plan names Jenkins checks (`Jenkins check:` entries)
   and the executor offers Jenkins, a validation run starts once the code is done. It
   starts the listed builds (each needs root approval) and reports their results.
4. **Your confirmation.** **Confirm changes** accepts the finished change.
5. **Server checks.** Only after confirmation, and only when the plan named them
   (`Server check:` entries) or the task lists deferred runtime checks, a server-check
   run executes them through the SSH executor; every action still needs root approval.
   Before confirmation, SSH actions may only inspect servers during planning and review;
   the implementer cannot use them.

The run page shows these steps in a **Delivery** panel. A split lists its tasks with the
status of each task's run. The next task starts automatically after each successful
one (**Start the next task automatically after each successful one** is on); it stops
at the first task that does not finish successfully, and before a task marked **Pause
before this task**, for example when you want to review the code before a task that
checks it on a server. **Start S-n** starts the next task by hand; a task whose run
failed can be started again with **Start S-n again**, and marking a task's run done
counts it as finished. A task run gets the overall goal and acceptance criteria, every
task with its outcome so far and its own step in a **Task split context** section,
instead of the whole conversation, so it stays within the model context. A stopped
**Allow all actions** on the parent also applies to the tasks and checks started after it.
A step that cannot run because the executor lacks Jenkins or SSH targets is shown as
skipped.

The run list puts a delivery under Running while code, validation or server checks run,
Needs you when a task, a check or an approval waits for you or failed, Ready for review
while it waits for your confirmation, and Done when it is confirmed and its server
checks finished. A split shows its progress (`Tasks 1/3`). A task header with
`"decompose": true` always splits, even a small plan.

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
If source or Git metadata changed after the checkpoint, continuation refuses to
proceed. Restart and follow-up establish a new baseline from current sources; they
never revert earlier changes.

## Conversation context

Each follow-up has a separate run ID and task file. The task contains the latest
Goal and a snapshot of prior task text, goals, public conclusions, validated stage
results and diffs. History is reference data; prior goals do not override the latest
Goal. Current source must be read again. Earlier tool logs and hidden reasoning
are not copied into the new prompt. The interface displays the earlier public
messages, then the new workflow stages.

History is flattened across turns and limited to 256 KB. An oversized history
produces a visible error asking for a new task with selected context. No history is
silently discarded. Usage monitoring applies to the selected run; each new turn
starts a fresh configured budget, unlike checkpoint continuation.

For a question, choose the **Answer only** mode. This sets server-generated `read_only`
metadata as well as instructions. Nonempty steps or proposed change paths are
rejected by plan validation, and a separate transition guard blocks implementation.
A successful reviewed answer finishes as `NO_CHANGES_REQUIRED` with its conclusion.
Changing back to **Change code** on the next turn removes the answer-only constraint.

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
`GET /api/session`, `/api/runs`, `/api/run` and `/api/analytics`.

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
Read-only requests never ask ([access](access.md#local-approval)). SSH tickets and
Jenkins builds always keep root-only approval.

Git and approved local actions resume the same opencode session inside one stage. A
missing/changed session ID stops continuation rather than starting fresh research.
Continue from a saved checkpoint still checks source and Git integrity; it never
blindly repeats an interrupted write. See [access](access.md).

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
