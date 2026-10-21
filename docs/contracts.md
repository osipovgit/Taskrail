# Instructions and response contracts

| Owner | Responsibility |
|---|---|
| `countersign/agents/*.md` | Role-specific method; no duplicate schema or budget |
| `application/policy.md` | Shared trust, paths, recovery and execution boundaries |
| `application/stage-instructions.json` | Stage-specific objective |
| `application/mode_rules.py` | Mode rule (Answer only, Design discussion, Split into tasks) from the task header, for browser and CLI tasks |
| `core/result-schemas.json` | Exact machine-readable response shape |
| `00-input/` | Frozen task, role sources and effective contract for this run |

Every response carries `"schema_version": 1`; any other value is rejected, and a
run or checkpoint with another contract version cannot continue. Models must return
one JSON object. The parser also accepts one unambiguous JSON object surrounded by
prose or Markdown; the surrounding text is neither evidence nor instructions.
Multiple objects, incomplete JSON, unknown fields and duplicate keys are invalid.
All result and tool paths are canonical absolute paths. Root aliases in task
metadata are labels; the engine resolves them.

Every final result contains status, summary, coverage, evidence, unverified and
blocking_gaps. Requirement IDs belong to verbatim task blocks and are assigned by
the server. The server-generated sections Workflow rules, Current turn, Task split
context and, in older tasks, Turn control are instructions without IDs. Each ID needs one outcome: satisfied, planned, contradicted, gap,
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

- Planner: structured steps (id, action, files, criteria, depends_on, checks),
  files_read and proposed_change_files. Every planned criterion needs an owning
  step, and the files of all steps must equal proposed_change_files.
- Implementer: completed_steps and changed_files, checked against the approved
  scope and observed source changes. IMPLEMENTED cannot leave planned requirements.
- Reviewer: input_complete and findings. Plan review can approve future work;
  result and no-change review cannot. An approval cannot contain defects or
  required gaps.

Evidence supplies an ID, an absolute path and a source line range, never the text: the
server takes the cited lines from the current file, binds them to a successful read
event that returned them and to the current source hash, and records the excerpt in
`evidence-bindings.json`. Whitespace is not significant, and only the start of very
long lines, which read tools cut, is compared.
`observations.json` keeps the complete validation ledger; `evidence.json` is a
bounded recovery subset of at most 60 records that never removes observations
needed for validation. Changed or unseen content cannot justify approval. A
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
twice per stage, with the error: the evidence ID and the actual text of the cited
range for a citation, the missing or unknown IDs for coverage. The session still has its
context and tools, so it can re-read and correct the result.

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
at most 200 lines, because the whole file can be larger than the model context. A
follow-up history over 24,000 bytes reaches the prompt the same way: the latest turn
inline and the indexed, readable `00-input/history.md`; `task.md` stays verbatim and
`task_sha256` covers it whole. A no-change completion still
needs independent review of all requirements. Text imported with `--plan-response`
is only an untrusted draft for fresh planning.

An explicit structured blocker always prevents progression, even if the model
labels it PLAN_READY or APPROVE. The draft is saved as `blocked-draft.json`; its
source and completion claims are not accepted, and the server records a BLOCKED
result with no edit authorization. Detected edits remain in the report.
`response-object.json` holds the decoded candidate; `response.raw.txt` keeps the
untouched response.

## Roles

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
twice per stage. A turn that ends without one JSON object (for
example, only announcing its next step, or a request written as XML or tool-call
markup) gets a reminder with the exact JSON formats in the same session, within the
same limit, before a format repair is tried. Every continuation also names the stage
role and its `request.md`, so a model whose session was summarized can re-read its
instructions and response schema. When the provider rejects a
turn because the session exceeded the model context window, the stage status is
`CONTEXT_EXCEEDED` and a read-only stage continues in a new session from its recorded
evidence (within `read_retries`); the implementer stops so Continue can inspect its edits.
The new session is told how much tool output the overflowing session received and
which calls returned at least 10,000 characters (at most five), so it does not repeat
them whole. Denial means the command is
skipped; consider the operator's alternative. Format repair cannot request execution.

Delivered output is cut at 24,000 characters. A stdout, stderr or Jenkins console
longer than 2,000 characters is also saved as plain text beside its snapshot, and then
only the first 8,000 characters are delivered inline
(`00-input/local/<stage>-<n>.stdout.txt`), named in the clipping notice, readable line
by line and citable as evidence while it matches the recorded output.

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

Runtime requirements may be marked satisfied only with cited, observed local,
SSH or Jenkins output snapshots that match successful executor results in the server ledger;
otherwise they stay deferred. Review must confirm that the recorded command and
output establish the requirement; exit code zero alone is insufficient.
