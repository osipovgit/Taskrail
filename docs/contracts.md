# Instructions and response contracts

| Owner | Responsibility |
|---|---|
| `taskrail/agents/*.md` | Role-specific method; no duplicate schema, policy or budget |
| `application/policy.md` | Execution boundaries, in `## All stages` and per-stage sections; each stage reads only its sections |
| `core/prompt-texts.json` | Every other model-facing text: stage and mode rules, plan format, response routing, executor routes, feedback and recovery notes |
| `application/instruction-modules.json` | Module selection metadata and keys into the prompt catalog |
| `core/result-schemas.json` | Exact machine-readable result and executor request shapes |
| `00-input/` | Frozen task, role sources and effective contract for this run |

Code selects texts by key and fills in `$placeholders`; it does not hold model-facing
prose. `00-input/contract.json` freezes the policy, the prompt texts and the schemas on the
first launch, and a continuation uses that frozen copy, so an update never changes the
instructions of a running task. A continuation is refused when the release's schemas
differ or the saved catalog lacks a required text key; start a new run to adopt the
updated contract. Frozen wording remains valid when all keys and schemas are compatible.
New task forms and child input snapshots use the current release, independently of another
run's active catalog. Runtime feedback, manifests, recovery, source-view guidance and
module prose use the active run's frozen catalog. Validator diagnostics describe the
current server's validation rules.

One public executor catalog supplies both route instructions and response alternatives.
SSH requires configured targets and a stage that permits it; implementation never
advertises ACTION_REQUEST. Jenkins requires configured jobs. Missing or unreachable
executors advertise neither remote schema. Prompts expose aliases, parameter names and
job approval modes, without repeating connection details that the approval screen shows.
The prompt budget matrix covers those capability combinations, workflow modes and
Python/shell/UI guidance together: planning and plan review remain below 10,500 instruction
bytes; implementation and result review below 9,000. It also bounds a representative
complete request plus role text. Variable user input, source packets and large inventories
still consume the configured model context allowance.

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
allowed; Not ToDo records excluded outcomes and their owning task IDs. In-place runs
retain their exact approved file boundary.

Review lines use the assigned requirement labels. A failure needs its problem;
`gap`, `n/a` and `later` need their explanations. An explained `n/a` is valid in
no-change and integration reviews as well as reviews of edits. Models cannot
override observed changes, granted scope, check records or the derived verdict.
Executor claims need exact snapshot lines too; a prose summary alone is not proof.

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
binding records every contributing observation and its exact line ranges, retaining
the primary event fields for compatibility. Repeated partial reads do not erase
earlier complete observations. Besides the declared roots, a citation may name source
views, executor snapshots and the preimages under `00-input/preimages`: the original
files a review compares, for example to show a removed line.

Oversized JSON can have a server-created `source_views` entry: a losslessly formatted
copy under `00-input/source-views`. Search and read only relevant view windows and cite
the view path and line numbers. Source and view hashes bind the copy to its original;
changed originals or modified views invalidate its evidence. Creating a view does not
make its contents observed. Raw and formatted values remain untrusted data, and
neither proves runtime success. Independent semantic review remains required.

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

A failed `read`, `glob`, `grep` or `list` call (a missing file, an out-of-range
offset, a directory, an aborted read), any tool call rejected for invalid arguments
before it ran, and an opencode or provider error after which the model still
reached its final answer are kept as warnings, not stage failures, so a final result
or executor request in the same turn is still handled. A failed read is not evidence
and does not waive required evidence. Permission denials, failed writes, and errors
after or without a final answer keep their safeguards.

A final result that fails validation first goes back to the same session, at most
three times per stage. Schema failures identify a stable error code and JSON pointer;
provenance errors identify up to five failing citations. When a citation's lines never
reached the session in full, the correction carries their current text (at most 60
lines per citation, never from a protected file). Only the citations included in the
feedback can become delivered evidence after the receiving turn completes, so the
session checks its claim against them; otherwise the correction
names the bounded missing windows. Repeated identical planner rejection
after same-session correction stops automatic fresh research retries. The session
keeps its context and tools and edits only the lines the feedback names; every problem
of `plan.md` or `review.md` names its line. When a review has no correction left, a
requirement whose citations it never confirmed becomes a gap that says so, instead of
failing the stage.

A plan or review still invalid after the corrections gets one full attempt with tools
and the validation error; its file keeps its text. Validation errors name requirements
by the request's `R<n>` labels; a split task's requirement may also be named by its
parent's ID when that ID names exactly one. The implementer gets no repair attempt.
A full attempt preserves existing edits and does not replay completed writes or
checks. Research recovery receives bounded observed source
material and keeps unresolved requirements explicit. `recovery.md` starts with an
index: each recorded call with its target, window, size and the line range of its
block in the file. The recovery prompt names the index lines and asks for windows of
at most 200 lines, because the whole file can be larger than the model context.
Index sizes are derived from the saved output; older observations need no
`saved_chars` field. Original truncation and source provenance remain unchanged. A
follow-up history over 24,000 bytes reaches the prompt the same way: the latest turn
inline and the indexed, readable `00-input/history.md`; `task.md` stays verbatim and
the frozen input integrity guard covers it whole. A no-change completion still
needs independent review of all requirements. Text imported with `--plan-response`
is only an untrusted draft for fresh planning.

Source citations recognize both plain numbered reads and the CLI's outer
`<content>` or `<file>` envelope, including a first line directly after the opening
tag. Literal tags inside numbered source lines remain text; tool footers do not
supply source evidence. Clipped, duplicate, reordered or stale lines cannot validate
a citation. A missing-read correction requires the cited source range, not a
cosmetic edit to the saved plan or additional unrelated citations.

An explicit structured blocker always prevents progression, even if the model
labels it PLAN_READY or APPROVE. The draft is saved as `blocked-draft.json`; its
source and completion claims are not accepted, and the server records a BLOCKED
result with no edit authorization. Detected edits remain in the report.
`response-object.json` holds the decoded candidate; `response.raw.txt` keeps the
untouched response.

## Plan file

The planner's only writable file is `<run>/plan.md`. The server writes its template on
the first attempt (one `R<n> →` line per requirement, with `runtime` already filled in
for runtime requirements and, when the run may change code, `all tasks` for global
constraints) and reads it when the session
ends; the file survives an interrupted or overflowing session. After a context
stop, a fully validated ready proposal advances to independent plan review; an
invalid one supplies exact validation errors to the bounded recovery attempt.
An exact native read-before-overwrite or edit `oldString` no-match error becomes a
warning only after a later successful native read and write of the same server-approved
file in the same session,
before the final response. This applies to the planner's plan and the implementer's
allowed files, never to read-only stages. The original rejection and
the read/write event references remain recorded; unresolved errors still stop the stage.
opencode remembers reads per process, and each turn after an executor request is a new
process of the session, so every turn attaches the stage's run file (`plan.md` or
`progress.md`) and opencode reads it at the start; project files are never attached.
This classification executes no tools and never retries a writer. Read ranges are
evidence locations, not edit coordinates: edits must match freshly read content.
The saved plan still passes full validation and independent review.
No source, coverage or scope check is relaxed. The request labels requirement blocks with `R<n>` and
names the project map. The format:

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

`runtime` may be followed by `: <check>`; without it the requirement text is the check.
`all tasks` makes the requirement an obligation of every task (it needs at least one
task). `Read:` lists `path:from-to` ranges the planner read; they are validated like any
citation and delivered as source to the task's implementer, so a split task, which is
implemented directly from the reviewed plan, starts with the planner's findings.

Keys accept Markdown emphasis and list fields accept bullet styles. Field values
retain literal underscores, backticks and command text; a complete code wrapper
around a file path is removed without changing its contents. Dependencies accept
`T1` or `Task 1`, separated by commas, semicolons, `and`, or list bullets. Every token
must parse; unknown text cannot silently remove a dependency. Duplicate fields are
rejected. Every problem is
reported at once with its line, back to the same session: an unknown or missing
requirement line, a task without files, requirements, results or checks, an unknown,
self or cyclic dependency, a requirement split between tasks without a distinct
`[scope]` for each part, a gap under any decision but blocked, or a task count the
decision rules out (split needs two tasks, single exactly one, no change none). A blocked plan
authorizes nothing. A planner result that still fails goes to one full attempt with
tools. Error messages name requirements by label.



Custom `agent_source` directories take precedence over bundled roles, and updates
never overwrite installed custom roles. Each role must contain the exact line
`Instruction contract: 1.` after its frontmatter; a missing declaration fails
before any model runs. Review a custom role against `taskrail/agents/` before adding the
declaration, or select the maintained roles with `deploy/install.sh --agents=bundled`.
Managed opencode profiles are named `taskrail-<role>-<run suffix>`, and their permissions come from the
engine, not from role frontmatter. Each stage records the source path, role hash,
contract hash and request hash; the UI shows this provenance. Editing a managed
profile is not a supported configuration method.

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
around it ignored; no field or argument is changed. Only a Git request that can change
state must be the entire response. A request with a wrong shape (an unknown or missing
field, a wrong version, an empty reason, a wrapped Git write) runs nothing: the same
session is told what to fix, at most twice per session, and after that the turn ends as
an invalid result. Multiple objects, duplicate keys and malformed JSON are not requests.
`cwd` is a declared root or an existing directory inside one. A
response with `cwd` and `argv` but without `"status": "LOCAL_REQUEST"` or
`schema_version` executes nothing; the same session is told what is missing, at most
twice per stage. Planner and reviewer stages cannot request `--fix`, `--write`,
in-place or `sed -i` options; such a request is rejected before approval.

An approved command may still change files. Files Git ignores (caches, reports, build
output) are not source and are never fingerprinted. Other changed files are adopted
into the run's source state, recorded with the action in `local-actions.json` and the
run state, listed in the report under **Changed by approved commands**, and named to the
session, which is told whether it may keep them. Git metadata changed by a command
still stops the run. A push through GIT_REQUEST waits for the operator's personal
decision; **Allow all actions** does not cover it.

A turn that ends without its valid stage result or an executor
request (for example, only announcing its next step or using tool-call markup) gets
a reminder of the stage-specific format in the same session, within the same limit,
before repair is tried. Every continuation also names the stage
role and its `request.md`, and preserves its Markdown file or terminal-line response
format. When the provider rejects a
turn because the session exceeded the model context window, the stage status is
`CONTEXT_EXCEEDED` and a read-only stage continues in a new session from its recorded
evidence (within `read_retries`), unless the planner's saved proposal passes the full
plan validator and can proceed directly to plan review. The implementer stops so
Continue can inspect its edits.
The new session is told how much tool output the overflowing session received and
which calls returned at least 10,000 characters (at most five), so it does not repeat
them whole. An exhausted provider quota or billing limit (`provider.quota`, "usage
limit", "insufficient quota", HTTP 402) is retried like a broken transport by default.
With `stop_on_provider_limit: true` it stops the stage at once, because a new session
would fail the same way; Continue the run after the limit resets. A short rate limit
is always retried.

When the provider or its gateway breaks off a turn (an error with no answer, no failed
tool and no permission denial), the same session continues after a pause of 1, 3 and
then 5 minutes, at most three times per stage, for every role including the
implementer. The session keeps its context and the changes it already made, which the
source guard has checked; it is told the error and asked to continue from where it
stopped. The pause does not count as active stage time, and Stop still works. This is
not a new writer, so nothing is replayed; when the continuations are spent the stage
ends as before and Continue stays available. Under `stop_on_provider_limit: true` an
exhausted quota is not continued. Denial means the command is
skipped; consider the operator's alternative.

All roles disable automatic compaction. `model_context_tokens` (one window, or one per
model with a `default`) defaults to 94,208
and `context_reserve_tokens` to 8,192; the reserve must be positive and smaller than
every window; each role uses its model's window. Request, role and attachment sizes
are recorded in bytes for diagnostics. They are not token counts and
cannot refuse a model turn. Permission to read a file does not mean its entire contents
enter the session.

During execution, the latest reported provider input, including read/write cache,
is checked against that capacity separately from cumulative token usage. A boundary
or compaction marker stops the session, including on continuation startup and the
final event drain. An explicit provider overflow also stops it. Missing usage reports
remain unknown; byte counts and cumulative usage cannot substitute for measured input.
See [context limits](deployment.md#context-limits) for configuration. A bounded context handoff may
start a fresh writer session from existing edits and progress notes; other writer
interruptions are never replayed. Before a fresh session starts, progress notes larger
than 8 KiB are archived verbatim and replaced with bounded excerpts. Their growth
during an active session never itself triggers a context stop. Repeated
overflow without changed source or working notes stops automatic handoffs.

An unavailable `invalid` tool sentinel is a rejected request that executed nothing.
When it precedes a completed final `DONE`, it remains a warning and the saved
artifact still passes the ordinary requirement and source-evidence validation.
Without completion, an isolated unavailable-tool rejection receives bounded
same-session guidance. Permission denials, failed writes and unrelated errors
retain their normal failure handling; narrative mentions of `DONE` do not complete
a turn.

Short local and Git outputs are delivered inline, capped at 24,000 characters.
Long local output is delivered as status, exit code, independent stream previews and
a digest. A stdout, stderr or Jenkins console longer than 2,000 characters is also
saved as plain text beside its snapshot (`00-input/local/<stage>-<n>.stdout.txt`).
Short stderr remains visible beside long stdout. Read exact saved lines before
citing a summary. Output copies remain citable only while they match their ledger.

SSH and Jenkins build continuations show only the latest ticket, with bounded
previews and output-file references. Each ticket has a write-once snapshot and
separate long-stream text files under `00-input/ssh`; repeated observation verifies
their integrity without rewriting them. Earlier tickets stay in the durable ledger
and are not replayed into each model turn. Older cumulative snapshots remain valid
historical artifacts and are never rewritten into the newer representation.

```json
{"schema_version":1,"status":"ACTION_REQUEST","action":{"targets":["qa-node-1"],"script":"uname -a\n","files":{},"reason":"Inspect kernel version","timeout_seconds":30}}
```

An ACTION_REQUEST is available only when the SSH executor is installed. It is
recorded in `execution.json` after root approval. `UNKNOWN` and rejected tickets are
never retried silently.

```json
{"schema_version":1,"status":"JENKINS_REQUEST","jenkins":{"server":"ci","job":"shop-tests","operation":"tests","build":"last","parameters":{},"reason":"Read the latest test results","timeout_seconds":60}}
```

A JENKINS_REQUEST is available only when the executor has a Jenkins configuration.
`status`, `console` and `tests` read `"last"` or a numbered build without a UI decision;
their results are snapshots under `00-input/local`. `build` uses `"build": "new"`,
only configured parameter names, and a ticket in `execution.json` approved by root
or by the executor's root-configured job policy (`approval: none`).

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
