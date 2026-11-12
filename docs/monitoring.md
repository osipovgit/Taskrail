# Monitoring and recovery

The UI shows public messages, tool calls, conclusions, source evidence and per-stage
usage. It does not expose hidden reasoning. The right sidebar summarizes elapsed
time and observed tokens; stage cards show steering timeouts and instruction provenance.
The first stage opened by Continue from checkpoint carries a continuation marker and
the operator’s verbatim note in the stage body and its Activity log. Subsequent attempts
keep their own origin. Alternating unchanged requests or transport errors share their
previous counts within the round. A changed draft, source or newly observed project
lines can make the same request useful again.

| Metric | Meaning |
|---|---|
| Observed tokens | Sum of reported step totals, including failed attempts |
| Input/output/cache/reasoning | Provider counters; categories may overlap |
| Last/peak input | Per-request observations, not full context-window occupancy |
| Wall time | Start to finish/current time, including pauses |
| Tool calls/errors | Distinct observed calls and latest status |
| Repeated reads | Identical read arguments within an attempt |
| Failed-attempt usage | Usage without a validated result; not a semantic quality score |

Missing usage means **unknown**, not zero. The stage context percentage compares
provider-reported input with the configured reserved capacity; no byte estimate or
cumulative usage supplies a missing observation. Duration, launches, token usage and
tool calls remain available for diagnostics.

## Recovery settings

| Setting | Default | Effect |
|---|---:|---|
| `timeout_seconds` | 3600 | Active model-stage time before pausing for steering. Operator approval waits pause its clock. |
| `transport_retries` | 3 | Fresh sessions after broken transport. Context rotation and corrections have independent progress checks. |
| `max_integration_corrections` | 3 | New full-cycle correction tasks for one rejected integration. Zero disables them. |
| `model_context_tokens`, `context_reserve_tokens` | 94208, 8192 | Per-model window and headroom. See [context limits](deployment.md#context-limits). |

After a timeout use **Continue from checkpoint**. The operator can add a note, and
the failed stage receives fresh time and retry counters. Previously accepted stages
and verified file changes are retained. See [task controls](task-controls.md).

## Analytics

**Analytics** in the task list (CLI: `taskrail analytics`) sums every run in the
run store: outcomes and success rate, recorded model time, reported tokens and
continuations, and per model and per stage the attempts, the first-try share (model
attempts the server accepted without a same-session correction, of those that recorded
their corrections), failed attempts, rejections (corrections sent back to the session,
with the most frequent reasons, paths and numbers blanked), recoveries, tokens and time. Runs in the trash are not counted. Missing
usage is reported as zero tokens, so compare models only on runs with telemetry.

During a live session, two consecutive file reads that return only previously delivered
complete lines trigger a hint in the next model request. It also detects alternating
files and narrower windows. The hint appears once per streak; new lines, changed text
or an intervening action let research proceed. Each stage uses its own visible context.
The activity counter separately counts calls with identical arguments.

## Artifacts

| File | Purpose |
|---|---|
| `run.json`, `checkpoint.json` | Ordered stages and safe continuation state |
| `00-input/` | Task, settings, role sources, contract, preimages |
| `NN-stage/stage.json` | Status, duration, provenance, allowance and diagnostics |
| `request.md`, `agent.md`, `permissions.log` | Effective request/profile/preflight |
| `events.jsonl`, `stderr.log` | Model messages, tool calls and process diagnostics. The UI derives usage from these events. |
| `events.raw.jsonl` | Original opencode 2.x events before normalization |
| `tool-result.md` | Latest feedback sent to a continued session, created on its first continuation |
| `result.json`, `evidence-bindings.json` | Validated result and source/event bindings |
| `plan.md`, `NN-plan/plan.md` | The planner's plan file, and the copy each planning attempt accepted |
| `00-input/project-map.md` | Neutral file inventory and landmarks the server wrote before planning |
| `evidence.json`, `recovery.md` | Source-versioned recovery data; clipping stays explicit |
| `findings.json`, `validation.json`, `handoff.md` | Pageable review feedback, long validation errors and saved public session notes |
| `changes.diff`, `report.md` | Actual edits and human review report |
| `00-input/local/`, `00-input/remote/` | Numbered command receipts by stage and text sidecars for long output. Remote approval tickets are named by ID. |
| `NN-check/verify-NN.log` | Output of a settings verification command |

Numbering reflects attempts in execution order, not fixed role numbers. Recovery
keeps bounded source reads (up to 60 records / 240,000 characters); clipped data is
not complete evidence. Current source hashes invalidate obsolete records. The UI
shows the latest 300 public events; raw JSONL retains the complete captured stream.

For diagnostics, share the affected stage, run report and evidence for the failed
claim. A repair returns all outstanding findings together. A changed plan, changed
source or changed set of findings merits another review. When the same work and set
recur, the writer receives different-strategy guidance before a no-progress stop.

Polling continues while text is selected, but DOM updates pause during a pointer
drag or a nonempty text selection. Clear the selection to display fresh data on
the next polling cycle. This protects copied text and does not pause the worker.

## Slow planning and invalid output

Inspect role provenance before increasing timeouts: an imported custom role can
contradict the current output contract. Use maintained bundled roles or update the
custom method without copying schemas or budgets into it. The role declaration is
checked before model execution.

Compare tool durations with stage wall time. Hundreds of short reads can still
require many slow model round trips and repeatedly processed context. Scope research
to unresolved criteria and their dependencies.
Mandatory operations unavailable under runtime policy should produce a precise gap,
not an exhaustive substitute scan. Supply needed history as permitted task evidence
when Git execution is unavailable. Model latency and service load require provider
telemetry; event logs alone cannot separate them.

Planner and reviewer stages submit saved Markdown. Validation feedback names missing
inputs, citations or contract fields so the agent can correct the draft. A proposed
planner blocker goes to independent plan review. A provider compaction event ends
the session. Saved drafts, delivered evidence and public notes support recovery.
See [context limits](deployment.md#context-limits).

Stage headers display `planner · 5 min 5 s / 1 h`: active time and its limit. The
clock updates once per second using server clock alignment without rebuilding message
nodes. Selection pauses DOM timer updates. Terminal stages keep the recorded elapsed
duration and effective attempt limit; only the worker establishes a timeout. Below the
clock, `Context 55% · 47,310 of 86,016 tokens` compares the session's context with its
model's input capacity (`Peak context` once the stage ended). It is the input the
provider reported for the latest finished step (uncached plus cache read and write).
Without a report, the card shows `Context unknown` and its capacity. Reports arrive
at step ends, so a running step retains the latest measured value until another
report arrives. Repeated turns can increase cumulative usage without increasing the
latest input by the same amount; cumulative totals and source bytes never determine
this percentage or a context stop. Historical byte-based estimates are ignored. Launch counts are diagnostic.

Git/local executor operations appear in the activity log as tool calls. They retain
one stage ID, session ID and cumulative active-time limit. Operator approval pauses
the timer indefinitely; ordinary command execution consumes the remaining time.
The separate SSH executor uses its own action timeout while the model waits.
Token counters remain observational; no cumulative-usage warning is shown.

An expanded Activity log keeps its heading and **Close log** button visible while
scrolling through its events. Closing returns keyboard focus to that log's summary.
The expanded task panel shows its title and Close button; outcome badges remain on
the graph node and the relevant stage rather than repeating between those controls.

Unreadable saved task records appear as **Saved data needs recovery** in Needs you.
The service continues other tasks and writes a separate `recovery-required.json`
diagnostic when the normal delivery record cannot be read. It never replaces the
damaged authority record or grants actions from it. Repair the saved data from a
trusted copy; a successful later inspection clears the diagnostic.
