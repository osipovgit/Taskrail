# Task controls and conversation turns

## State and actions

| Action | Required state | Result |
|---|---|---|
| Restart from scratch | No active workflow | Open the prefilled task form; submit explicitly to create a new run |
| Stop task | Running | Write a stop request; the worker cleans up opencode and saves an interruption checkpoint |
| Continue with extra budget | Eligible checkpoint; explicit confirmation | Add two attempts and one attempt timeout to the interrupted stage; retain consumption |
| Continue interrupted run | Eligible checkpoint and unchanged source | Append new attempts to the same run, starting at the interrupted stage |
| Send a follow-up Goal | Previous run stopped, no active workflow | Snapshot prior public evidence and start a new run from planning |
| Answer only | New or follow-up submission | Research and independent review, no implementation |
| Delete from history | Stopped/completed run, no active workflow | Move run and launcher artifacts to local trash; leave source files untouched |

Stop is cooperative. The worker checks requests at stage boundaries and while
waiting for opencode. Permission preflight, filesystem scans and short built-in checks
may finish before the request is observed. The UI shows the pending stop state.
No stored PID is signalled, so a reused PID cannot affect another process. The
existing process-group cleanup handles the opencode process and its children. Closing
the web page does not stop the worker. Stopping the managed application service
also requests this checkpoint-preserving interruption for its owned worker.

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

For a question, select **Answer only**. This sets server-generated `read_only`
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

Deletion holds the same global workflow lock as execution. Active runs, path
traversal, symlinked runs and symlinked trash/submission storage are rejected.
A child turn retains its snapshotted context even if its ancestor is removed.

## Local API

Same-origin and CSRF-token checks apply to every mutation (`POST /api/tasks`,
`/api/actions`, `/api/decision`). `/api/actions` accepts
`{"id":"run-id","action":"restart|resume|resume_budget|stop|delete"}`; `resume_budget`
is **Continue with extra budget**, and restart returns a `draft` without launching
anything. `/api/tasks` accepts the task fields plus `read_only`, and optionally
`parent_run` with `submission_mode` `restart`, `followup` or `answer`; without a
parent the mode is `new`. `/api/decision` answers one pending approval ticket with
`allow`, `deny` or `alternative`. Commands and settings stay server-owned. Reads use
`GET /api/session`, `/api/runs` and `/api/run`.

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
the execution lock and current worker checks continue to protect active tasks.
Deleting history moves artifacts to local trash and never changes project files.

CLI equivalent:

```sh
countersign resume /absolute/path/to/run --extend-budget
```
