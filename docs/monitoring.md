# Monitoring and budgets

The UI shows public messages, tool calls, conclusions, source evidence and per-stage
usage. It does not expose hidden reasoning. The right sidebar summarizes elapsed
time and observed tokens; stage cards show time allowances and instruction provenance.

| Metric | Meaning |
|---|---|
| Observed tokens | Sum of reported step totals, including failed attempts |
| Input/output/cache/reasoning | Provider counters; categories may overlap |
| Last/peak input | Per-request observations, not full context-window occupancy |
| Wall time | Start to finish/current time, including pauses |
| Tool calls/errors | Distinct observed calls and latest status |
| Repeated reads | Identical read arguments within an attempt |
| Compaction | Explicit structured markers only; `opencode run` usually emits none, so it shows as unknown |
| Failed-attempt usage | Usage without a validated result; not a semantic quality score |

Missing usage or compaction events means **unknown**, not zero. A context percentage
requires verified endpoint limits, complete latest-request usage and output reserve;
the model name and cumulative spend cannot supply it. Cost currency/rates are not
verified. Provider quotas, not these counters, enforce billing limits.

## Server settings

Edit `~/.config/countersign/settings.json` (or the explicit `--settings` file). The
opencode command, models and profile directory are described in
[deployment](deployment.md#opencode). Budget settings:

```json
{
  "timeout_seconds": 3600,
  "stage_timeout_seconds": 14400,
  "max_stage_attempts": 6,
  "read_retries": 3,
  "max_repairs": 3,
  "max_observed_tokens": 0
}
```

`timeout_seconds` bounds one attempt. `stage_timeout_seconds` and
`max_stage_attempts` bound one stage; its active time and launches are shared across
retries, repair and Continue. The run token limit is separate; zero disables
that limit. `budgets.json` reserves launches before spawning and records measured
elapsed time afterward. A hard crash without a duration retains the reserved time
conservatively. Explicit setting increases and UI continuation grants are recorded; Continue never
resets usage. **Continue with extra budget** adds a stage allowance after confirmation,
without increasing the run token cap. See [task controls](task-controls.md).

An interrupted writer is never automatically replayed. A source-compatible
checkpoint can be continued explicitly after reviewing the reason and allowances.
Cumulative usage has no warning threshold. Counters are for comparison, not context occupancy.

## Analytics

**Analytics** in the task list (CLI: `countersign analytics`) sums every run in the
run store: outcomes and success rate, recorded model time, reported tokens and
continuations, and per model and per stage the attempts, failed attempts, format
repairs, recoveries, tokens and time. Runs in the trash are not counted. Missing
usage is reported as zero tokens, so compare models only on runs with telemetry.

## Artifacts

| File | Purpose |
|---|---|
| `run.json`, `checkpoint.json` | Ordered stages and safe continuation state |
| `00-input/` | Task, settings, role sources, contract, preimages |
| `NN-stage/stage.json` | Status, duration, provenance, allowance and diagnostics |
| `request.md`, `agent.md`, `permissions.log` | Effective request/profile/preflight |
| `events.jsonl`, `stderr.log`, `response.raw.txt` | Raw evidence; response may be invalid JSON |
| `result.json`, `evidence-bindings.json` | Validated result and source/event bindings |
| `plan.md`, `NN-plan/plan.md` | The planner's plan file, and the copy each planning attempt accepted |
| `00-input/project-map.md` | Files, landmarks and requirement hints the server wrote before planning |
| `evidence.json`, `recovery.md` | Source-versioned recovery data; clipping stays explicit |
| `budgets.json` | Durable reservations, consumption and allowance changes |
| `changes.diff`, `report.md` | Actual edits and human review report |
| `NN-check/verify-NN.log` | Output of a settings verification command |

Numbering reflects attempts in execution order, not fixed role numbers. Recovery
keeps bounded source reads (up to 60 records / 240,000 characters); clipped data is
not complete evidence. Current source hashes invalidate obsolete records. The UI
shows the latest 300 public events; raw JSONL retains the complete captured stream.

For diagnostics, share the run index/report and affected stage, plus budgets and
evidence for retry issues. Redact secrets and sensitive source before sharing.

`max_repairs` (default 3, at most 5) limits plan repairs after plan review and repair
cycles after failed checks or result review; each stage gets at most one format repair.
`read_retries` (default 3, at most 3) limits read-only research retries. Tool calls remain diagnostic metrics.

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

A single unambiguous JSON object is decoded locally despite surrounding prose or
Markdown. Semantic coverage and source checks still apply to work proposals.
Explicit blockers produce a safe BLOCKED result with the unvalidated draft saved;
they never authorize implementation or approval. A repair call receives the original requirement IDs and cannot research
or manufacture missing evidence. Compaction remains unknown without a structured
marker; narrative recap text is not proof of a compaction event.

Stage headers display `planner · 5 min 5 s / 1 h · 54 min 55 s left` while running.
The clock updates once per second using server clock alignment without rebuilding
message nodes. Selection pauses DOM timer updates. Terminal stages keep the recorded
elapsed duration and effective attempt limit. `Timeout pending` means the UI clock
reached the limit; only the worker can establish the final timeout status. The launch
counter is retained internally for recovery control but is not displayed in stage cards.

Git/local executor operations appear in the activity log as tool calls. They retain
one stage ID, session ID and cumulative active-time limit. Operator approval pauses
the timer indefinitely; ordinary command execution consumes the remaining time.
The separate SSH executor uses its own action timeout while the model waits.
Token counters remain observational; no cumulative-usage warning is shown.
