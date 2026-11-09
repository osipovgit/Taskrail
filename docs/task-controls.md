# Task controls and conversation turns

## State and actions

| Action | Required state | Result |
|---|---|---|
| Restart from scratch (standalone run) | Stopped run | Open the prefilled task form; submit explicitly to create a new run once no run is active on its projects |
| Restart reviewed task (split child) | Latest attempt of the next unfinished task; no active writer | Start a linked attempt from the approved parent plan, directly at implementation; preserve previous edits and original preimages |
| Restart this phase (integration review, Jenkins validation, server checks) | Latest stopped attempt of the phase | Start the phase again under the same delivery; the earlier run stays one of its attempts |
| Correct integration findings | Rejected integration, no unfinished correction, remaining integration corrections | Start a fresh linked task with planning, plan review, implementation, local checks and result review; owned isolated branches also receive a verified commit |
| Stop task | Running | Write a stop request; the worker cleans up opencode and saves an interruption checkpoint |
| Continue from checkpoint | Eligible checkpoint, unchanged source, no active run on its projects | Append new attempts to the same run, starting at the interrupted stage; a stage that reported **Blocked** can continue too, with your note answering its question; an interrupted or blocked implementer first inspects its existing edits |
| Send a follow-up Goal | Previous standalone run stopped, no active run on its projects | Snapshot prior public evidence and start a new run from planning; a task or phase run has no follow-up, use Continue with a note or a follow-up of its parent |
| Answer only | New or follow-up submission | Research and independent review, no implementation; the reviewed answer opens the report and is the `answer` of `taskrail status` |
| Design discussion | New or follow-up submission | Like Answer only, but the reviewed summary is a design document, saved as `design.md`; follow-ups refine it, a **Develop** follow-up implements it |
| Confirm changes | A finished code change with planned server checks, after integration review for a split and any Jenkins validation | Accept the change; the server checks start only now |
| Mark as done / Move back from Done | Stopped run | Move the run to the Done group, or return it to its computed group; nothing else changes |
| Delete from history | Stopped/completed run; no active run of its split or delivery | Move run and launcher artifacts to local trash; leave source files untouched |

A run on the same project holds back only what would start a worker: Continue, a
follow-up and a task or phase restart. The run page names the active run's project
instead of hiding the reason; Mark as done, Delete and the restart form stay usable.

Each run page shows its mode (**Develop**, **Answer only** or **Design discussion**;
explicit splits show **Split into tasks**); the run list shows the mode when it is
not Develop.

The run list groups runs by what they need:

| Group | Runs |
|---|---|
| Running | Starting or running, not waiting for you |
| Needs you | A pending UI decision, an SSH or Jenkins ticket waiting for root approval, or a stop without a successful result (errors, budgets, interruptions); highlighted in yellow |
| Ready for review | A finished change: waiting for your review, or for your confirmation before server checks |
| Done | Confirmed with its server checks finished, finished without changes, or marked done; collapsed until opened or searched |

## Delivery of a code change

Every top-level Develop task follows task understanding, planning, independent plan review, implementation,
checks and result review. A split dispatches authenticated children in dependency
order, followed by independent integration review over the combined original and
corrective diff. Each child receives its complete assignment, prerequisite outcomes
and immutable `00-input/parent-task.md`. Later work appears under Not ToDo.
A child starts at implementation and cannot split again. See [contracts](contracts.md)
for plan and review rules, [task format](task-format.md#worktree-isolation) for commit
and file scope, and [checks](checks.md) for executable acceptance.

Rejected integration may start one correction per rejected review, bounded by the
parent's frozen `max_integration_corrections`. A correction plans, receives plan review, implements,
checks and receives result review; owned task branches also get verified commits.
Success starts another integration review. Auto-continue controls both automatic
correction and repeat review. Failed or interrupted corrections require inspection:
eligible Continue is available, but corrective writers cannot Restart. Unresolved
Git writes block delivery. After the configured number of integration corrections, the delivery waits for the operator.
New local catalog checks are allowed; new remote bindings require parent replanning.

Planned Jenkins validation follows integration. Planned server checks wait for
**Confirm changes**, then the isolated executor's root approval. Confirmation binds
source/Git fingerprints, accepted results and their links. Every server request and
phase restart rechecks them; drift requires fresh review and confirmation. Without
server checks the completed change is Ready for review, with no confirmation wait.
Unconfigured Jenkins/SSH phases are skipped; integration review is never skipped.
Manual done marks cannot replace accepted prerequisite results or independent review.

The Delivery graph shows tasks by dependency, numbered corrections and every phase.
Open a node to inspect its stages, decisions, report and diff. Earlier attempts are
collapsed but remain accessible; `#parent/child` opens a node directly. Child and phase
runs appear under their parent, including in searches. **Pause before this task**
stops automatic dispatch; **Start S-n** starts the next eligible task explicitly.

Child retries preserve earlier edits and original preimages. Between attempts,
external changes to tracked or trackable files are named under **Changed outside
this task** and delivered to the implementer for inspection. Ignored files do not
count. Edits during a running stage still trip the integrity guard. Changed
requirements or scope require parent replanning. A restarted child retains its sealed
assignment; it cannot become a detached planner or follow-up conversation.

Links are persisted before worker launch and serialized with Pause, auto-continue
and confirmation. A launch interrupted before its worker starts becomes LAUNCH_ERROR;
it is never retried automatically. Repeat integration review invalidates later
validation and confirmation while preserving prior phase attempts.

Stop is cooperative: it saves a checkpoint and cleans up the owned provider process
group, without signalling stored PIDs. Short checks may finish first. Closing the
page does not stop work; stopping the managed service requests interruption.
Continue retains frozen inputs, original preimages and approved scope. Source/Git
must match its checkpoint. Notes are passed verbatim but cannot change authority.
For a changed split child use Restart reviewed task; for a standalone run use Restart.
None of these operations rolls back edits.

Only `run_format: 2` runs are supported. Continue requires the exact application
release identity; after a code update use Restart. A run with another format requires
a new task and can be archived with `taskrail history archive-old`. An unsupported
run cannot supply parent context or start a child or delivery phase.

Allow all actions and its family-wide revocation are described once in
[access](access.md#approval). A done mark applies to the outcome it was given for;
continuation with a different outcome returns the run to its computed group.

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
only the sections it needs. Smaller histories stay inline unchanged. Usage is recorded per run.

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
Restoring an unsupported format does not make it executable; inspect its artifacts
and create a new task.

Deletion holds the run's lock, so its worker cannot start meanwhile. Active runs, path
traversal, symlinked runs and symlinked trash/submission storage are rejected.
A child turn retains its snapshotted context even if its ancestor is removed.

## Local API

Same-origin and CSRF-token checks apply to every mutation (`POST /api/tasks`,
`/api/actions`, `/api/decision`). `/api/actions` accepts
`{"id":"run-id","action":"restart|resume|stop|delete"}`, and a continuation may add `"note"`. Restart returns a `draft` for a standalone run,
launches a linked attempt for an eligible split child, integration, validation or server phase,
and refuses corrective writers. `/api/tasks` accepts the task fields plus the booleans `read_only`,
`design`, `decompose` and `auto_approve`, and optionally `parent_run` with `submission_mode`
`restart`, `followup`, `answer` or `design`; without a parent the mode is `new`. `/api/decision` answers one pending approval ticket with
`allow`, `deny` or `alternative`; an `allow` may add `"allow_all": true`. Commands and settings stay server-owned. Reads use
`GET /api/session`, `/api/runs`, `/api/run` and `/api/analytics`. `/api/actions` also
accepts `epic_next`, `epic_auto_on`, `epic_auto_off`, `confirm`, `integration_review`, `integration_correct`,
`done`, `reopen`, `revoke_auto_approve`, and with a `"task"` field `epic_pause` and
`epic_unpause`.

## Automation from the CLI

When the browser cannot be used, for example a chat bot on the server, the CLI starts
and controls runs through the same launcher, validation and run store. Each command
prints one JSON object and returns at once; the task runs in a detached worker.

```sh
taskrail submit --root shop=/srv/shop --goal @goal.md --mode answer --allow-all
taskrail status RUN                       # status, answer, worker activity, approval, delivery step
taskrail decide RUN alternative --text "Use tox instead"
taskrail action RUN resume --note "python3 is installed now"
taskrail submit --json payload.json       # the fields of POST /api/tasks
```

`--mode` is `develop` (the default), `answer`, `design` or `split`; every top-level task runs in
[isolated worktrees](task-format.md#worktree-isolation).
`--followup RUN` and `--restart RUN` continue a conversation; a text option may name a file as `@FILE`. `action` accepts the
`/api/actions` actions. For a standalone run, `action RUN restart` prints the saved
`draft`; submit the edited fields with `parent_run` and `submission_mode: "restart"`
in the JSON payload. For a split child, `action CHILD_RUN restart` launches a new
linked attempt of the same reviewed task directly, and `action PHASE_RUN restart` runs
integration, validation or server checks again under their parent. A correction can
only Continue from an eligible checkpoint; otherwise replan the parent.
`submit --restart` or `--followup` naming a task
or phase run is rejected because a detached run would lose its parent.
Automatic steps of a split (the next task, bounded integration correction and review,
Jenkins validation, server checks after confirmation) need the managed service.

## Decisions and continuation

Approval rules, Allow all actions, family inheritance and revocation are owned by
[access](access.md#approval). Decisions use exact tickets; waiting does not consume
active stage time. Stop remains available. An alternative or note is feedback, never
a new permission or goal.

Git and approved local requests resume the same provider session; a missing or changed
session ID stops continuation. `local-actions.json` records argv, approval, source
snapshot and environment identity before execution. UNKNOWN actions cannot run again
merely because their reason changed or the task continued.
A repeated identical local/Git request on unchanged work prompts a change of
strategy before another execution. Live remote observations can change independently.
Review feedback and explicit Continue start a fresh stage round.

## Continuing after a pause

Choose **Continue from checkpoint** or run `taskrail resume /absolute/path/to/run`.
Add a steering note to clarify the remaining work. The worker checks source, Git and
frozen inputs before resuming the interrupted stage. Each explicit continuation
starts fresh timeout and retry counters; usage history is retained.
