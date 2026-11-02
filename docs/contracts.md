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
mode combinations: 10,500 instruction bytes for planning/review, 9,000 for
implementation/result review. Variable user input and source data are additional.

A request has three parts: `# Task` with the task fields under readable headings and a
label before each requirement block (`[R1]`, `[R2 runtime]`, `[R3 constraint]`, placed at
the requirement's own field and offset), the stage's instructions, and a compact Context
JSON. Stable requirement IDs stay server-side; the model uses labels.

No role writes a JSON result. The planner writes `plan.md` and a reviewer `review.md`,
both in the run directory and attached to every turn, and each ends with `DONE`; the
implementer ends with `DONE:` or `BLOCKED:`. The server derives the canonical stored
result, version 1, from them. Executor requests are the only JSON responses and keep
version 1. Unknown wire versions and unsupported run or checkpoint versions are
rejected. Continuations and validation feedback retain the stage's original format.
The request parser also accepts one unambiguous object surrounded by prose or
Markdown; the surrounding text is neither evidence nor instructions.
Multiple objects, incomplete JSON, unknown fields and duplicate keys are invalid.
All result and tool paths are canonical absolute paths. Root aliases in task
metadata are labels; the engine resolves them.

Every stored final result contains status, summary, coverage, evidence, unverified
and blocking_gaps. Requirement IDs belong to substantive task blocks and are
assigned by the server. Titles, section headings, single label lines ending with
`:`, current behavior and known entry points remain context rather than separate
acceptance obligations.
The prompt shows the task once, with labels before its requirement blocks;
the original task snapshot remains verbatim. Typed fields provide the requirement
boundaries; their Markdown headings cannot change authority. Only authenticated
server context supplies workflow instructions. A reviewed child receives its sealed
task projection, while untrusted original task and history files remain archival
artifacts outside the model's readable inputs. Each ID needs one outcome: satisfied, planned, contradicted, gap,
deferred, not_applicable or not_evaluated. `not_evaluated` is allowed only in BLOCKED results, when
a shared blocker prevented validation. Only runtime requirements may be deferred.
Required missing evidence means BLOCKED, even when the result format is valid. A plan names
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
- Implementer: no JSON result. It ends with `DONE: <what changed>` (one or two
  sentences; on a task branch they become the commit message) or
  `BLOCKED: <what it needs>`, the last such line of its final message. The server
  derives everything else: changed_files from the source scan, completed_steps from
  the approved contract, checks from their records. It reports no requirement
  outcomes or citations; the independent review judges every requirement. A final
  message without either word gets a correction in the same session and no other
  attempt. Besides its allowed files it keeps `<run>/progress.md` (Done,
  Remaining, Verify), which survives an interrupted, timed-out or overflowing
  session: every turn has it attached, and a later session does not re-check
  finished work. It is a note, never evidence, so a rejected overwrite of it is only
  a warning.
- Reviewer: writes `review.md`, a `Summary:` line and one line per requirement:
  `R1: done: <citations>`, `R1: fails: <citations> (<problem>)`, `R1: gap: <missing
  input>`, `R1: n/a: <why it does not apply>`, `R1: later: <runtime check>` and, in
  plan review, `R1: planned`. Other lines are free notes. The server derives a finding
  from each failure, the blocking gaps, input completeness and the verdict: a gap
  blocks, a failure requests changes, otherwise the review approves. Plan review can
  approve planned work; result and no-change review cannot. `n/a` covers a conditional
  requirement whose condition did not occur and never blocks.

Documentation and test work are valid standalone deliverables when the user requests
them. The planner and reviewer reject only artificial companion tasks that separate
tests or documentation from the implementation that owes them. Each task still needs
observable acceptance criteria, planned files and appropriate verification. On an
authenticated task branch, necessary additional files within permitted roots remain
allowed; Not ToDo names later work to leave alone unless the task needs a part of it,
which the summary names. In-place runs
retain their exact approved file boundary.

Review lines use the assigned requirement labels. A failure needs its problem;
`gap`, `n/a` and `later` need their explanations. An explained `n/a` is valid in
no-change and integration reviews as well as reviews of edits. Models cannot
override observed changes, granted scope, check records or the derived verdict.
Executor claims need exact snapshot lines too; a prose summary alone is not proof.

Single lines (`:41` or `:41-41`), multiple citations separated by commas or semicolons,
and a final period after a citation or parenthesized explanation are valid. Prose in
parentheses does not add citations; text or extra citations after that explanation
remain invalid. Quoted paths may contain spaces and parentheses.

During plan review only, `planned` and `fails` may cite the current `plan.md` or the
accepted planner's `result.json`. The current and archived plan copies must match,
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
contains decisions and task contracts, omitting repeated coverage, read lists and
prior verdicts. Empty optional context fields are omitted.
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
unresolved proof remains a blocking gap. The same-session correction limit is three;
a still-invalid plan or review gets one complete attempt with tools. Implementers
never receive a blind replay. Citation corrections deliver only bounded current
source windows; accepted evidence must be attributable to the receiving session.
An explicit blocker prevents progression even if the model claims approval.
Raw responses and rejected drafts remain diagnostic artifacts.

Transport retry, context handoff, budgets and output delivery are described in
[monitoring](monitoring.md) and [deployment](deployment.md#context-limits).

## Plan file

The planner writes `<run>/plan.md`, attached at every turn. It survives interruption.
A ready proposal recovered after a context stop still passes complete validation and
independent plan review. The server labels requirement blocks with `R<n>`.
Read ranges identify evidence, never edit coordinates. Use freshly read content for
edits. The format:

```markdown
Decision: split | single | no change | blocked
Summary: one or two sentences (an answer or design document goes in ## Answer)

## Requirements
- R1 → T1 [roles/ntp], T2 [roles/web]
- R2 → done: project/README.md:12-18
- R3 → runtime
- R4 → all tasks
- R5 → gap: the Jenkins job name is not in the task

## T1: Fix lint in roles/ntp
Depends on: none
Files: project/roles/ntp/tasks/main.yml, project/roles/ntp/defaults/main.yml (new)
Read: project/roles/ntp/tasks/main.yml:1-40, project/.ansible-lint:1-12
Done when:
- ansible-lint roles/ntp reports no var-naming findings
Verify:
- ansible-lint roles/ntp
Notes: optional pointers for the implementer

## After the change
- Jenkins check: ci/ansible-lint: BRANCH=main passes
- Server check: run ansible-playbook --check site.yml on the controller
```

A `done:` or `contradicted:` outcome starts with an explicit citation list, then an
optional explanation in parentheses. Separate files with commas or semicolons;
`/exact/read/path:7-42,43-156,157-169` cites all three ranges of the same file.
Backtick-quote the whole citation for paths containing spaces. References inside
the explanation are prose, not additional evidence. `Read:` accepts only citation
lists, without explanations. Paths are absolute, root-alias-relative, or relative
to the only declared root; basenames are never searched for or guessed. Every
explicit range still needs matching observed current lines. A diff alone does not
establish that an unrun check passed.

Run instructions and result artifacts (`request.md`, `plan.md`, `review.md`,
`recovery.md`) never prove completion, even if observed. Path feedback names the
affected requirements; changing the attempt path or inventing a source handle does
not fix it. Assign ongoing obligations to tasks; cite current source or executor
snapshots for completed work, or declare a blocking evidence gap.

`runtime` may be followed by `: <check>`; without it the requirement text is the check.
`all tasks` (optionally followed by a parenthesized reason) makes the requirement an
obligation of every task; it needs at least one task and is not a completed claim.
`Read:` lists `path:from-to` hints for the implementer's first reads; these hints are
not evidence that the planner observed the source. A split task starts from the
reviewed plan and its independently validated citations.

Plan syntax, dependency parsing, scopes and field diagnostics are specified in
[task format](task-format.md). Invalid plans receive all line-specific errors before
independent review; BLOCKED plans authorize no edits.

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
session is told what to fix, at most three times in a row (a valid request resets the
count), and after that the turn ends as an invalid result. Multiple objects, duplicate
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
Written verification remains explicit deferred work where no configured recipe is
selected. The existing approval route still decides whether an exact
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
