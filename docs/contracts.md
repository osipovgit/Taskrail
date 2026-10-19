# Instructions and response contracts

| Owner | Responsibility |
|---|---|
| `countersign/agents/*.md` | Role-specific method; no duplicate schema or budget |
| `application/policy.md` | Shared trust, paths, recovery and execution boundaries |
| `application/stage-instructions.json` | Stage-specific objective |
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
the server. Each ID needs one outcome: satisfied, planned, contradicted, gap,
deferred or not_evaluated. `not_evaluated` is allowed only in BLOCKED results, when
a shared blocker prevented validation. Only runtime requirements may be deferred.
Required missing evidence means BLOCKED, even when the JSON is valid.

- Planner: structured steps (id, action, files, criteria, depends_on, checks),
  files_read and proposed_change_files. Every planned criterion needs an owning
  step, and the files of all steps must equal proposed_change_files.
- Implementer: completed_steps and changed_files, checked against the approved
  scope and observed source changes. IMPLEMENTED cannot leave planned requirements.
- Reviewer: input_complete and findings. Plan review can approve future work;
  result and no-change review cannot. An approval cannot contain defects or
  required gaps.

Evidence supplies an ID, absolute path, source line range and exact quote. The
engine binds it to a successful read event and the current source hash.
`observations.json` keeps the complete validation ledger; `evidence.json` is a
bounded recovery subset of at most 60 records that never removes observations
needed for validation. Changed or unseen content cannot justify approval. A
matching quote proves provenance, not the model's interpretation, so independent
review remains necessary. Only server records prove executed checks. The exact
schema is supplied in each request; do not copy it into custom roles.

An explicit `File not found` or out-of-range line offset from an exploratory read,
and any tool call rejected for invalid arguments before it ran, is kept as a
warning, not a transport failure. The failed read is not evidence and
does not waive required evidence. Permission denials, failed writes and other tool
errors keep their safeguards.

Format repair receives the saved response, the validation error, the schema and the
server-assigned requirements. Each stage gets at most one. It has no tools (or
read-only tools with `format_repair_tools: read`, which may also re-read the
`recovery.md` evidence of earlier attempts of the same stage), never edits, even for the
implementer, cannot invent requirement IDs or quotations, and must not research. An
implementer repair reports only edits already present; changed files are still
checked against the observed source. If the repair reports BLOCKED because it
cannot rebuild the result without tools, the stage gets one full attempt with tools
and the original validation error. Research recovery receives bounded observed source
material and keeps unresolved requirements explicit. A no-change completion still
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
GIT_REQUEST, LOCAL_REQUEST or (when advertised) ACTION_REQUEST object as the entire
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
twice per stage. Denial means the command is skipped; consider the operator's
alternative. Format repair cannot request execution.

```json
{"schema_version":1,"status":"ACTION_REQUEST","action":{"targets":["qa-node-1"],"script":"uname -a\n","files":{},"reason":"Inspect kernel version","timeout_seconds":30}}
```

An ACTION_REQUEST is available only when the SSH executor is installed. It is
recorded in `execution.json` after root approval. `UNKNOWN` and rejected tickets are
never retried silently.

Runtime requirements may be marked satisfied only with quoted, observed local or
SSH output snapshots that match successful executor results in the server ledger;
otherwise they stay deferred. Review must confirm that the recorded command and
output establish the requirement; exit code zero alone is insufficient.
