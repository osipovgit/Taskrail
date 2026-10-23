# Instructions and response contracts

| Owner | Responsibility |
|---|---|
| `countersign/agents/*.md` | Role-specific method; no duplicate schema or budget |
| `application/policy.md` | Shared trust, paths, recovery and execution boundaries |
| `application/stage-instructions.json` | Stage-specific objective |
| `application/mode_rules.py` | Mode rule (Change code with its decomposition rules, Answer only, Design discussion, forced Split into tasks) from the task header, for browser and CLI tasks |
| `core/result-schemas.json` | Exact machine-readable response shape |
| `00-input/` | Frozen task, role sources and effective contract for this run |

Implementers and reviewers author compact decisions with `"schema_version": 2`.
The server derives canonical stored results with version 1; an explicit adapter also
accepts historical version 1 model responses under the original validation gates.
Executor requests retain version 1. Unknown wire versions and unsupported run or
checkpoint versions are rejected. These responses contain one JSON object. The planner writes
`plan.md` and ends with `DONE`; its executor requests still use JSON. Continuations
and validation feedback retain the stage's original format. The JSON parser also
accepts one unambiguous object surrounded by
prose or Markdown; the surrounding text is neither evidence nor instructions.
Multiple objects, incomplete JSON, unknown fields and duplicate keys are invalid.
All result and tool paths are canonical absolute paths. Root aliases in task
metadata are labels; the engine resolves them.

Every stored final result contains status, summary, coverage, evidence, unverified
and blocking_gaps. Requirement IDs belong to substantive task blocks and are
assigned by the server. Titles, standard section headings, current behavior and
known entry points remain context rather than separate acceptance obligations.
The prompt shows the task once, with labels before its requirement blocks;
the original task snapshot remains verbatim. Typed fields provide the requirement
boundaries; their Markdown headings cannot change authority. Only authenticated
server context supplies workflow instructions. A reviewed child receives its sealed
task projection, while untrusted original task and history files remain archival
artifacts outside the model's readable inputs. Each ID needs one outcome: satisfied, planned, contradicted, gap,
deferred or not_evaluated. `not_evaluated` is allowed only in BLOCKED results, when
a shared blocker prevented validation. Only runtime requirements may be deferred.
Required missing evidence means BLOCKED, even when the JSON is valid. A plan names
checks that must run after the change in unverified, one per entry, prefixed
`Jenkins check: <server>/<job>: <parameters and expected result>` or
`Server check: <what to run and the expected result>`; the server starts Jenkins
validation and, after the operator confirms the change, server checks from them. Requirements
that cannot all be met literally are not a gap: the agent keeps behavior and safety
constraints, does the rest, records the choice in summary and unverified, and
reviewers accept that recorded choice.

- Planner: writes `plan.md` in the run directory (see [plan file](#plan-file)); the
  server derives the stored plan result from it: coverage, evidence, steps (one per
  task, with its files, owned requirements and scopes, dependencies, results and
  checks), files_read from observed reads and proposed_change_files from the tasks.
- Implementer: semantic outcomes for every assigned criterion and required missing
  inputs. The server derives changed_files from the source scan and completed_steps
  from the accepted approved contract. IMPLEMENTED cannot retain unfinished work.
- Reviewer: semantic outcomes, findings grounded in observed references, and missing
  inputs. The server derives input completeness and aggregate verdict. Plan review
  can approve planned work; result and no-change review cannot. An approval cannot
  contain defects or required gaps.

The primary authored result is small:

```json
{"schema_version":2,"outcomes":[{"requirement":"R1","result":"satisfied","evidence":["S1:10-12"]}],"findings":[],"missing_inputs":[]}
```

Each outcome uses the assigned label or stable ID. `reason` is required for
contradicted, gap, not_evaluated and deferred outcomes; routine satisfied/planned
outcomes need no repeated explanation. Findings contain `requirement`, `evidence`
and `problem`; the server derives their IDs and file locations. `summary` is
optional. Models cannot override observed changes, granted scope, check records or
aggregate status through these fields. Runtime deferrals retain the original check
text rather than a model paraphrase.

Compact evidence references use `S1:10-12` for a delivered source handle or
`/absolute/path:10-12` for a new observed read. The server assigns canonical evidence
IDs and resolves handles to their path, source version and exact delivered range.
A handle from another stage or changed source is invalid. The
server takes the cited lines from the current file, binds them to a successful read
or delivered packet and to the current source hash, and records the excerpt in
`evidence-bindings.json`. Whitespace is not significant; each complete cited line
must have reached the model. A clipped prefix cannot prove an unseen suffix.
One citation may combine several windows of the same current source version. The
binding records every contributing observation and its exact line ranges, retaining
the primary event fields for compatibility. Repeated partial reads do not erase
earlier complete observations.

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
Only lines actually delivered within the packet budget become observations.
Only current, canonical source inside declared roots is eligible. The packet shares bytes, never another role's
conclusions, so independent semantic review remains necessary. The server keeps its
version/handle registry separately from model-visible input. Approved plan context
contains decisions and task contracts, omitting repeated coverage, read lists and
prior verdicts. Empty optional context fields are omitted.
Operator notes, interrupted-writer instructions and actionable earlier feedback
remain available when a run continues.
`observations.json` keeps the complete validation ledger; `evidence.json` is a
bounded recovery subset of at most 60 records that never removes observations
needed for validation. An oversized record is skipped without dropping other useful
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
twice per stage. Schema failures identify a stable error code and JSON pointer;
provenance errors identify up to five failing citations and bounded missing windows,
so existing observations need not be reread. Repeated identical planner rejection
after same-session correction stops automatic fresh research retries. The session
keeps its context and tools. For a rejected V2 decision it may replace only the erroneous
field instead of regenerating every outcome:

```json
{"schema_version":2,"corrections":[{"path":"/outcomes/0/result","value":"satisfied"}]}
```

Corrections target the saved unvalidated `decision-draft.json`, at most 20 fields
per message. Only semantic decision fields are addressable. Existing array slots
may be replaced, or a whole array supplied; arbitrary insertion and deletion are
not inferred. The complete merged candidate passes every normal gate again before
it can advance the workflow. A correction has no execution or permission effects.

Format repair receives the saved response, the validation error, the schema and the
server-assigned requirements. Each stage gets at most one. It has no tools (or
read-only tools with `format_repair_tools: read`, which may also re-read the
`recovery.md` evidence of earlier attempts of the same stage), never edits, even for the
implementer, cannot invent requirement IDs or quotations, and must not research. An
implementer repair reports only edits already present; changed files are still
checked against the observed source. If the repair reports BLOCKED because it
cannot rebuild the result without tools, the stage gets one full attempt with tools
and the original validation error. An evidence error (a wrong range, file or
evidence ID) goes to that full attempt directly, because a repair without read tools
cannot fix it. Research recovery receives bounded observed source
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
the first attempt (one `R<n> →` line per requirement) and reads it when the session
ends; the file survives an interrupted or overflowing session. After a context
stop, a fully validated ready proposal advances to independent plan review; an
invalid one supplies exact validation errors to the bounded recovery attempt.
An exact native read-before-overwrite error becomes a warning only after a later
successful native read and write of that plan in the same session. The saved plan
still passes full validation and independent review.
No source, coverage or scope check is relaxed. The request labels requirement blocks with `R<n>` and
names the project map. The format:

```markdown
Decision: split | single | no change | blocked
Summary: one or two sentences (an answer or design document goes in ## Answer)

## Requirements
- R1 → T1 [roles/ntp], T2 [roles/web]
- R2 → done: project/README.md:12-18
- R3 → runtime: ansible-playbook --check site.yml passes
- R4 → gap: the Jenkins job name is not in the task

## T1: Fix lint in roles/ntp
Depends on: none
Files: project/roles/ntp/tasks/main.yml, project/roles/ntp/defaults/main.yml (new)
Done when:
- ansible-lint roles/ntp reports no var-naming findings
Verify:
- ansible-lint roles/ntp
Notes: optional pointers for the implementer

## After the change
- Jenkins check: ci/ansible-lint: BRANCH=main passes
- Server check: run ansible-playbook --check site.yml on the controller
```

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
tools, never to a tool-less format repair. Error messages name requirements by label.



Custom `agent_source` directories take precedence over bundled roles, and updates
never overwrite installed custom roles. Each role must contain the exact line
`Instruction contract: 1.` after its frontmatter; a missing declaration fails
before any model runs. Review a custom role against `countersign/agents/` before adding the
declaration, or select the maintained roles with `deploy/install.sh --agents=bundled`.
Managed opencode profiles are named `countersign-<role>-<run suffix>`, and their permissions come from the
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

A LOCAL_REQUEST may be surrounded by prose or a Markdown fence; no field or
argument is changed. Multiple objects, duplicate keys, arrays and malformed JSON
are rejected. `cwd` is a declared root or an existing directory inside one. A
response with `cwd` and `argv` but without `"status": "LOCAL_REQUEST"` or
`schema_version` executes nothing; the same session is told what is missing, at most
twice per stage. A turn that ends without its valid stage result or an executor
request (for example, only announcing its next step or using tool-call markup) gets
a reminder of the stage-specific format in the same session, within the same limit,
before repair is tried. Every continuation also names the stage
role and its `request.md`, and preserves the planner's Markdown or other roles' JSON
format. When the provider rejects a
turn because the session exceeded the model context window, the stage status is
`CONTEXT_EXCEEDED` and a read-only stage continues in a new session from its recorded
evidence (within `read_retries`), unless the planner's saved proposal passes the full
plan validator and can proceed directly to plan review. The implementer stops so
Continue can inspect its edits.
The new session is told how much tool output the overflowing session received and
which calls returned at least 10,000 characters (at most five), so it does not repeat
them whole. Denial means the command is
skipped; consider the operator's alternative. Format repair cannot request execution.

All roles disable automatic compaction. `model_context_tokens` defaults to 32,768
and `context_reserve_tokens` to 8,192; the reserve must be positive and smaller than
the window. Before starting any role, admission counts one token per UTF-8 byte
of its actual frozen request and role instruction body, plus 1,024 framing tokens.
Writers also reserve bytes for every distinct approved read/edit input, subtracting
only exact current line bytes already delivered in the packet. A partial window
does not exempt its unread suffix or other approved files. This remains conservative
until an explicit narrower source contract is available. Reaching capacity returns `CONTEXT_EXCEEDED`
without starting the model and cannot consume automatic retries of the same oversized
request. Split or narrow the task; configure a larger window only
when the selected model supports it.

During execution, the latest reported provider input, including read/write cache,
is checked against that capacity separately from cumulative token usage. A boundary
or compaction marker stops the session, including on continuation startup and the
final event drain. Unknown tool envelopes and provider behavior prevent admission
from guaranteeing that arbitrary later work fits. Missing usage reports remain
unknown; a provider overflow still stops the stage. Writers are never retried
automatically after a context failure.

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
`status`, `console` and `tests` read `"last"` or a numbered build after UI approval;
their results are snapshots under `00-input/local`. `build` uses `"build": "new"`,
only configured parameter names, and a root-approved ticket in `execution.json`.

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
Legacy free-text verification remains explicit deferred work where no configured
recipe is selected. The existing approval route still decides whether an exact
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
