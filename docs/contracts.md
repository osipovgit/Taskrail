# Instructions and response contracts

| Owner | Responsibility |
|---|---|
| `taskrail/agents/*.md` | Role-specific method; no duplicate schema, policy or budget |
| `application/policy.md` | Execution boundaries, in `## All stages` and per-stage sections; each stage reads only its sections |
| `core/prompt-texts.json` | Every other model-facing text: stage and mode rules, plan format, response routing, executor routes, feedback and recovery notes |
| `application/instruction-modules.json` | Module selection metadata and keys into the prompt catalog |
| `core/result-schemas.json` | Exact machine-readable result and executor request shapes |
| `00-input/` | Frozen task, role sources and effective contract for this run |

Code selects catalog keys and fills `$placeholders`. Each run freezes role sources,
policy, texts and schemas in `00-input/`; their hashes must remain unchanged.
`run_format: 2` is independent of executor `schema_version: 1`. Unsupported run
formats cannot Continue, Restart or supply parent context. Archive them with
`taskrail history archive-old` and start a new task. Continue also requires the
same application release identity; a same-format run from another release may
Restart. The identity hashes application Python, JSON and instruction Markdown,
independent of installation path. Frozen catalogs must equal the release catalog;
there is no adoption of old wording or missing-key compatibility.

The executor catalog advertises only configured, stage-permitted routes; the
implementer never receives SSH actions. Prompt-budget tests cover capability and
mode combinations: 5,000 instruction bytes for task understanding, 10,500 for planning/review, 9,000 for
implementation/result review. Variable user input and source data are additional.

A request has three parts: `# Task`, stage instructions and a compact Context JSON.
Understanding receives the original fields once in `Context.task_fields`; later stages
read them under the task headings. After interpretation, requirements
use labels such as `[R1]`, `[R2 runtime]` and `[R3 constraint]`. Exact source text may be
labelled in place; an interpreted obligation appears separately from the original input.
Stable requirement IDs stay server-side; the model uses labels.

Task understanding writes `understanding.json`, a resumable draft containing a summary
and obligations with `text`, `kind` (`task` or `constraint`) and exact source quotes.
Each source names an input field and a verbatim quote, plus a one-based occurrence when
the quote repeats. The server checks those references, resolves character spans and
assigns IDs. These checks prove provenance, not semantic completeness: the planner and
independent reviewer also compare the complete original task. Background does not become
an obligation merely because it occupies a paragraph. Conditions, ordering and conflicting
instructions must survive extraction. Explicit runtime check identities stay server-owned.
The understanding role uses the planner's configured model unless `models.understanding`
is set.

An input interpretation defect in planning or plan review returns as `REINTERPRET_TASK`
with a summary and original source quotes. It returns automatically to understanding;
unchanged obligations retain IDs, and the saved plan must pass validation and independent
review again. It cannot alter an authenticated child's assignment. Continue retains
the accepted requirement list and resumes its checkpointed stage.

The planner writes `plan.md` and a reviewer `review.md`,
both in the run directory and attached to every turn. The planner replies
`Ready for server plan checks.` and the reviewer replies `DONE`. The
implementer ends with `DONE:` or `BLOCKED:`. The server derives the canonical stored
result, version 1, from them. Executor requests keep version 1; an input-correction
message is a workflow transition and executes no command. Unknown wire versions and unsupported run or checkpoint versions are
rejected. Continuations and validation feedback retain the stage's original format.
The request parser also accepts one unambiguous object surrounded by prose or
Markdown; the surrounding text is neither evidence nor instructions.
Multiple objects, incomplete JSON, unknown fields and duplicate keys are invalid.
All result and tool paths are canonical absolute paths. Root aliases in task
metadata are labels; the engine resolves them.

Execution and review results contain status, summary, coverage, evidence, unverified
and blocking_gaps. The understanding result records its accepted requirements instead
of claiming source evidence or completion. The original task snapshot remains verbatim.
Typed fields preserve input boundaries; their Markdown headings cannot change authority.
Only authenticated
server context supplies workflow instructions. A reviewed child receives its sealed
task projection, while untrusted original task and history files remain archival
artifacts outside the model's readable inputs. Each ID needs one outcome: satisfied, planned, contradicted, gap,
deferred, not_applicable or not_evaluated. `not_evaluated` is allowed only in BLOCKED results, when
a shared blocker prevented validation. Only runtime requirements may be deferred.
A confirmed missing prerequisite blocks the run. A repairable gap in a plan goes
back to the planner. A plan names
checks that must run after the change in unverified, one per entry, prefixed
`Jenkins check: <server>/<job>: <parameters and expected result>` or
`Server check: <what to run and the expected result>`; the server starts Jenkins
validation and, after the operator confirms the change, server checks from them. A conflict
between Goal and Constraints that changes implementation is a blocking gap naming the
exact decision needed. Neither implementation nor review may silently choose a new goal
or transfer an excluded deliverable from another task.

- Planner: writes `plan.md` in the run directory (see [plan file](#plan-file)); the
  server derives the stored plan result from it: coverage, evidence, steps (one per
  task, with its files, owned requirements and scopes, dependencies, results and
  checks), files_read from observed reads and proposed_change_files from the tasks.
- Implementer: no JSON result. It submits `DONE: <what changed or why no change was needed>`, including
  any rationale the task requires, or
  `BLOCKED: <what it needs>`, the last such line of its final message. The server
  derives everything else: changed_files from the source scan, completed_steps from
  the approved contract, checks from their records. It reports no requirement
  outcomes or citations; the independent review judges every requirement.
  The review request names the exact proposed commit message or no-change note.
  The reviewer may cite its wording and must verify code and checks independently.
  The report links the submitted text. After approval each changed repository
  receives the reviewed message and a commit receipt. No-change submissions keep
  their reason in the run without creating an empty commit. A final
  message without either word gets a correction in the same session and no other
  attempt. Besides its allowed files it keeps `<run>/progress.md` (Done,
  Remaining, Verify), which survives an interrupted, timed-out or overflowing
  session: every turn has it attached, and a later session does not re-check
  finished work. It is a note, never evidence, so a rejected overwrite of it is only
  a warning.
- Reviewer: writes `review.md`, a `Summary:` line and an outcome for every requirement:
  `R1: done: <citations>`, `R1: fails: <citations> (<problem>)`, `R1: gap: <missing
  input>`, `R1: n/a: <why it does not apply>`, `R1: later: <runtime check>` and, in
  plan review, `R1: planned`. Plan review allows a separate `fails` line for each defect of the same requirement. The server derives a finding
  from each failure, the blocking gaps, input completeness and the verdict: a gap
  blocks, a failure requests changes, otherwise the review approves. Plan review can
  approve planned work; result and no-change review cannot. `n/a` covers a conditional
  requirement whose condition did not occur and never blocks.

### Findings across plan revisions

The server sends the planner all open findings in one pageable packet. Each new defect
gets a stable ID such as `F3-1` (review stage 3, finding 1). On each revision the planner
replaces `## Finding responses` in `plan.md` with an answer for every open ID.

```markdown
## Finding responses
- F3-1: fixed: T1 now runs the parser on empty input before committing.
- F3-2: disputed: T1 already checks the retry path under Verify.
```

The next plan reviewer reads the responses and checks the current plan and source.
Each issued ID needs its own decision, observed citation and reason in `review.md`.

```markdown
- F3-1: closed: /work/run/plan.md:24 (T1 checks empty input)
- F3-2: open: /work/run/plan.md:25-27 (the retry check still covers only successful calls)
```

An open decision supplies a failing outcome for its requirement. If all its issues
close, include the requirement's ordinary outcome, such as `R1: planned`. Report
new defects on their own `R1: fails: …` lines. Only open IDs return for repair.
A planner's disagreement can close a finding after independent confirmation.
Continue uses the feedback packet of the checkpoint. If a corrected interpretation
replaces the original requirement, a remaining defect can keep its ID under its new
owner with `F3-2: open: R2: /work/run/plan.md:25 (reason)`.

Documentation and test work are valid standalone deliverables when the user requests
them. The planner and reviewer reject only artificial companion tasks that separate
tests or documentation from the implementation that owes them. Each task still needs
observable acceptance criteria, planned files and appropriate verification. On an
authenticated task branch, necessary additional files within permitted roots remain
allowed; Not ToDo names later work to leave alone unless the task needs a part of it,
which the summary names.

Review lines use the assigned requirement labels. A failure needs its problem;
`gap`, `n/a` and `later` need their explanations. An explained `n/a` is valid in
no-change and integration reviews as well as reviews of edits. Models cannot
override observed changes, granted scope, check records or the derived verdict.
Executor claims need exact snapshot lines too; a prose summary alone is not proof.

Single lines (`:41` or `:41-41`), multiple citations separated by commas or semicolons,
and a final period are valid. Each citation may have a parenthesized explanation:
`source.py:1-3 (first reason), other.py:4 (second reason)`. Every explicit range is
validated; references inside explanations remain prose. Bare prose between citations
or unbalanced parentheses are rejected. Backticks may enclose the whole citation or
only its path; quoted paths may contain spaces and parentheses.

During plan review only, `planned` and `fails` may cite the current `plan.md` or the
accepted planner's `result.json`, named explicitly by `Context.plan_result`. Earlier
results and review feedback may describe a superseded proposal. The current and archived plan copies must match,
and the result must match the proposal the workflow is reviewing. These lines still
need observation in the active session. A plan defect in a runtime check requests
replanning without claiming that the check ran. Plan artifacts never prove `done`,
and final, integration and delivery reviews still require source or executor evidence.

Compact evidence references use `S1:10-12` for a delivered source handle or
`/absolute/path:10-12` for a new observed read. The server assigns canonical evidence
IDs and resolves handles to their path, source version and exact delivered range.
A handle from another stage or changed source is invalid. Absolute paths have the
same evidence rules as handles. The server takes the cited lines from the current
file and requires a successful read or delivered packet in the active attempt and
its exact opencode session. It binds the current source hash and excerpt in
`evidence-bindings.json`. Whitespace is not significant; each complete cited line
must have reached the model. A clipped prefix cannot prove an unseen suffix.
One citation may combine several windows of the same current source version. The
binding records every contributing observation and its exact line ranges. Repeated
partial reads do not erase
earlier complete observations. Besides the declared roots, a citation may name source
views, executor snapshots and the preimages under `00-input/preimages`: the original
files a review compares, for example to show a removed line.

Oversized JSON can have a server-created `source_views` entry: a losslessly formatted
copy under `00-input/source-views`. Search and read only relevant view windows and cite
the view path and line numbers. Source and view hashes bind the copy to its original;
changed originals or modified views invalidate its evidence. Creating a view does not
make its contents observed. Raw and formatted values remain untrusted data, and
neither proves runtime success. Independent semantic review remains required.

The same repair applies to canonical executor snapshots and preimages. Small missing
windows may be delivered in correction feedback. If a JSON output string is too long,
feedback points to its existing plain-text stream only after matching it to the exact
snapshot value. Read the relevant stream lines and cite them; pointers alone grant no
evidence, and the command need not run again. Other internal run artifacts and symlinks remain
excluded, including when a broad project root contains the run directory.

Stage prompts can carry a source packet of at most 4,000 serialized UTF-8 bytes,
with at most 80 previously observed numbered lines per range. Before a model runs,
the server can also read windows of at most 40 lines from exact Known entry point
paths and approved plan citations or change paths. Entry points accept canonical
absolute paths, root aliases or unambiguous single-root relative paths, optionally
with `:from-to`. Prose is not guessed as a path. Missing, protected, symlinked,
binary and oversized files are skipped; ordinary controlled reads remain available.
Only lines actually delivered within the packet budget become evidence for the
receiving session. Preparing a packet or correction does not grant that authority:
the exact payload must complete a turn in the expected session. Failed or interrupted
turns and text omitted by truncation grant no evidence authority. A new session must receive
the relevant source again or read it itself.
Only current, canonical source inside declared roots is eligible. The packet shares bytes, never another role's
conclusions, so independent semantic review remains necessary. The server keeps its
version/handle registry separately from model-visible input. Approved plan context
contains decisions, task contracts and deferred checks, omitting repeated coverage,
read lists and prior verdicts. Check bindings use the same `R<n>` labels as the
task; stored results retain stable requirement IDs. Empty optional context fields are omitted.
Operator notes, interrupted-writer instructions and actionable earlier feedback
remain available when a run continues. A split task's first request also carries
`outside_changes`: the files changed outside the split's tasks before it started.
`observations.json` keeps source discovery and attributed delivery records;
validation selects only the active attempt and session. Earlier observations may
seed a new source packet, but are not proof that its receiver read them.
`evidence.json` is a bounded recovery subset of at most 60 records that never removes
observations needed for validation. An oversized record is skipped without dropping other useful
records. Changed or unseen content cannot justify approval. A
matching citation proves provenance, not the model's interpretation, so independent
review remains necessary. Only server records prove executed checks. The exact
schema is supplied in each request; do not copy it into custom roles.

Recovery never upgrades a failed or partial read to source evidence. Required
unresolved proof remains a blocking gap. The session receives the complete validation feedback. Repeated failures on
unchanged work lead to a fresh session with the recorded evidence and diagnostics.
A writer inspects partial edits before proceeding. Citation corrections deliver only bounded current
source windows; accepted evidence must be attributable to the receiving session.
Repeated citations of one missing window share one correction entry. Exhausted
corrections retain exact path/range failures for the fresh attempt. Source scope is
checked before reading a citation or converting an unconfirmed review claim to a gap.
An explicit blocker prevents progression even if the model claims approval.

Native tool errors, including access denials, stay in opencode's conversation so the
agent can correct arguments, inspect partial edits or choose a permitted alternative.
They remain visible in the activity log with a red background. A completed turn goes
through normal result, evidence and source-integrity validation regardless of earlier
tool failures. An error never proves a successful read or write and never expands
permissions. There are no error-text-specific recovery exceptions or temporary read
grants. Raw responses and rejected drafts remain diagnostic artifacts.

If the process or provider interrupts a turn, the server returns bounded diagnostics
to the same uniquely identified session. It does not replay tools or roll back files.
The implementer inspects current source and may request a scoped
[Git restore](git-access.md) or repair the file directly, preserving earlier user edits.
Repeated interruptions with unchanged diagnostics and work trigger a change of
session. A persistently unchanged failure pauses for steering.
Source or Git integrity violations and unavailable session identity cannot be
silently recovered. Required work without a permitted solution remains a precise gap.

Ordinary Goal and Acceptance criteria may require local lint, syntax and test
commands. Assign that work to a task; `runtime` is a deferral outcome reserved for
requirements explicitly labelled runtime, not a synonym for executing a command.
Invalid deferrals are reported with other plan structure errors. Independently
checkable plan scope, coverage and task-contract defects are reported together
before citation source bytes are read. The planner’s final message submits its saved draft. A completed
correction event only records delivery of rejection feedback, never plan approval.

Transport retry, context handoff, timeouts and output delivery are described in
[monitoring](monitoring.md) and [deployment](deployment.md#context-limits).

## Plan file

The planner writes `<run>/plan.md`, attached at every turn. It survives interruption.
A ready proposal recovered after a context stop still passes complete validation and
independent plan review. The server labels requirement blocks with `R<n>`.
The planner and the next reviewer receive the same complete [findings file](#findings-across-plan-revisions).
Each task describes its intended result and how to verify it. For example:

```markdown
Decision: single
Summary: Correct the invalid variable name in the NTP role.

## Requirements
- R1 → T1
- R2 → T1

## T1: Correct the NTP role variable
Depends on: none
Files:
- project/roles/ntp/tasks/main.yml
- project/roles/ntp/defaults/main.yml
Read:
- project/roles/ntp/tasks/main.yml
- project/.ansible-lint:1-12
Done when: The default and all references use the corrected name and retain its value.
Verify:
- Run ansible-lint roles/ntp and inspect any remaining findings.
```

`Read` is optional. Use a file, a file with a line or range, or a list of these
references. Paths can be absolute, root-alias-relative, or relative to the only
root. Backtick-quote names with spaces or punctuation. A trailing `:N` or
`:N-M` selects lines even inside backticks. For a literal name ending in
`:N`, put an explicit range outside the quoted name, as in `` `report:2`:1-20 ``.
A parenthesized note stays with the task. A bare source path gives the child a
starting point for a bounded read. For `done` and `contradicted`, cite observed
lines that support the claim using the review citation format above.

A split task can name a parent executor report under `00-input/local`, `git`, `ssh`
or `checks` in its `Read` list. Taskrail binds selected report material to the
reviewed plan and gives the assigned child a read-only copy under
`00-input/plan-reports/`. Relevant command receipts and captured streams travel
with the report. A line range is a starting window into it. For a large JSON
report, use its original path in `Read`. The child can make its own readable view.
The receipt describes the original execution. Claims about the changed tree need
current verification.

`Files` contains exact paths only. A rejected pattern or inline explanation reports
the actual bullet's line number, including blank lines; valid bullets stay intact.
Replace patterns with discovered files and move scope explanations to `Notes`. Backtick-quote literal paths with spaces, commas or brackets. A bulleted task field such as `- Required checks: none` starts that field. Put local verification in the owning task’s `Verify` field.
The model sees those instructions in `Context.plan.steps[].verify`. The stored
plan retains them under `steps[].checks`. See [check ownership](checks.md#select-and-bind-checks).

Run instructions and result artifacts (`request.md`, `plan.md`, `review.md`,
`recovery.md`) never prove completion, even if observed. Path feedback names the
affected requirements; changing the attempt path or inventing a source handle does
not fix it. Assign ongoing obligations to tasks; cite current source or executor
snapshots for completed work, or declare a blocking evidence gap.

`runtime` may be followed by `: <check>`; without it the requirement text is the check.
`all tasks` (optionally followed by a parenthesized reason) makes the requirement an
obligation of every task; it needs at least one task and is not a completed claim.
Launch-snapshot read hints resolve to the child’s inherited snapshot.

Plan syntax, dependency parsing, scopes and field diagnostics are specified in
[task format](task-format.md). Invalid plans receive all line-specific errors before
independent review. A blocked planner draft grants no edits. The independent reviewer
checks the named missing prerequisite and permitted alternatives. A supported route
returns to planning. A confirmed missing prerequisite stops with its reasons, and
Continue reopens the planner with the operator’s clarification. An approval cannot
turn a blocked proposal into a successful no-change result. For each plan-review
verdict, the server checks that the reviewed JSON and Markdown still match the
accepted planner snapshot, including reviews consisting entirely of `planned` lines.

Custom roles require `Instruction contract: 1.` and are validated before model work.
Updates preserve custom roles; `deploy/install.sh --agents=bundled` selects maintained
ones. Runtime profiles are generated per role and run; permissions come from the
engine. Stages record role source/hash, contract hash and request hash for UI provenance.

## Executor requests

Executor requests replace the final result for one turn: return one complete
GIT_REQUEST, LOCAL_REQUEST or (when advertised) ACTION_REQUEST or JENKINS_REQUEST object as the entire
response and end the turn. They are not model function tools. The server validates
the request, waits for any required approval, records the result and resumes the
same opencode session in the same stage. Final schemas and evidence checks are
unchanged. See [access](access.md) and [Git access](git-access.md).

```json
{"schema_version":1,"status":"LOCAL_REQUEST","cwd":"/absolute/declared/root","argv":["python3","-m","unittest"],"reason":"Run the unit tests without changing source"}
```

Every request type is recognized the same way (`interactions/request_envelope.py`):
exactly one JSON object whose `status` names a request, with prose or a Markdown fence
around it ignored. Only a Git request that can change state must be the entire
response. A local command is taken as the model meant it (`interactions/local_intake.py`):
a missing `status` (when `argv` is given) or `schema_version` is filled in, other fields
are dropped, `command` or `cmd` may name the command, a command string is split, or run
with `bash -c` when it uses shell syntax, and a missing or relative `cwd` resolves
inside the single root or the named root alias. The command policy, the sandbox and any
approval see the resulting argv and cwd. A request that still has a wrong shape (a wrong
version, a non-list command, a wrong status, a wrapped Git write) runs nothing: the same
session is told what to fix, with the same progress detection as result validation. Multiple objects, duplicate
keys and malformed JSON are not requests. `cwd` must end up a declared root or an
existing directory inside one. Planner and reviewer stages cannot request `--fix`,
`--write`, in-place or `sed -i` options; such a request is rejected before approval.

Command permissions, sandbox boundaries, approvals and source/Git checks are owned
by [access](access.md). Remote request examples and executor setup are in
[SSH executor](ssh-executor.md); controlled Git syntax is in [Git access](git-access.md).
A request is not execution proof. SSH/Jenkins snapshots contain exactly one ticket;
immutable long-output files remain beside it. Reobservation verifies those bytes.
UNKNOWN remote outcomes require inspection and are never replayed automatically.

Configured checks can run without model-authored execution requests. Server
settings own `check_recipes`, each with `kind`, `phase`, an exact `request`, an output
`adapter` and an optional short `description`. Planner context exposes only recipe
IDs, descriptions, kinds, phases and adapters. It never includes command arguments
or server configuration values. Plan review receives the selected recipe-to-criterion
bindings, existing configured checks, and only their relevant catalog entries.
The planner selects existing recipes with:

```markdown
## Check selections
- lint: R3
- integration-tests: R4, R5
```

These bindings are reviewed with the plan. The engine materializes a closed
`check_specs` record per selection: `id`, `recipe_id`, assigned runtime `criteria`,
`phase` and empty `parameters`. Task headers may supply the same typed records.
Tasks cannot introduce recipes, override commands or supply parameter overrides.
Explicit runtime criteria without a selected recipe remain deferred when the plan
assigns them to their delivery phase. The existing approval route still decides whether an exact
configured request may execute; selection grants no permission. Local checks run
after edits, Jenkins validation uses its delivery phase, and server checks require
the operator's confirmation of the changes.
See [configured checks](checks.md) for operator settings and examples.

Runtime evidence must belong to the assigned check and criterion, its exact
request digest and the source/Git snapshot it verified. Check results separate
execution status from passed, failed or unknown assessment. A matching failed
check may substantiate contradiction; an unrelated successful command or stale
result cannot establish satisfaction. Generic historical execution snapshots remain
readable evidence, but are not silently upgraded to checked runtime acceptance.
Review still determines semantic sufficiency; exit code zero alone is insufficient.
