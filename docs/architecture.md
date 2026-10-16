# Architecture

The browser is the primary interaction surface, served by a managed user service.
The application has one execution engine and two entry points: CLI and HTTP
submission both invoke `application.live.execute_task`; the web worker does not
implement a second workflow. State is persisted on disk, outside project roots.
UI updates read the ordered stage index and public event stream.

| Location | Responsibility |
|---|---|
| `countersign/cli.py`, `__main__.py` | CLI parsing and module entry point |
| `application/` | Workflow, stage artifacts, checkpoints, budgets, prompts and research recovery |
| `interactions/` | Same-session executor turns, exact-command approvals, active clock and local commands |
| `git/` | Controlled Git grammar, scope checks, isolated process execution and output snapshots |
| `core/` | Result contract, schema validation, file/path utilities and stop/read-only guards |
| `infrastructure/` | opencode launch (1.x direct, 2.x through an adapter), JSONL parsing, permission profiles |
| `observability/` | Public progress, usage and compaction telemetry |
| `executor/` | Separate system service: peer-authenticated socket, immutable tickets, root-only approval, SSH transport |
| `web/server.py` | Loopback HTTP API and static resources |
| `web/service.py`, `health.py` | Managed process lifecycle and bounded readiness check |
| `web/submissions.py`, `worker.py` | Validated task creation and detached workflow launch |
| `web/history.py`, `requests.py`, `lifecycle.py` | Editable task drafts, conversation history and lifecycle controls |
| `web/static/` | Browser JavaScript, CSS, HTML and theme handling |
| `deploy/` | Offline release installation, CLI wrapper and systemd units |
| `agents/` | Editable role templates, frozen per run |
| `tests/` | Workflow, contracts, permissions, API, telemetry and DOM regressions |
| `tools/`, `quality/` | Development quality gates and the reviewed Wemake debt baseline |
| `docs/`, `examples/` | Documentation and example tasks |

Dependency direction: CLI/web -> application, interactions and git (the workflow
layer) -> infrastructure/observability -> core. Core imports nothing outside core;
the executor imports only core and itself. Architecture tests enforce these
boundaries. No plugins, message bus, service container or database are used. New
entry points must call the existing workflow instead of adding an execution path.

Run artifacts: `00-input/`, numbered stage directories, `run.json`, `checkpoint.json`,
the report and the diff. Declared roots, allowed writes, Git metadata checks and the
global execution lock enforce task boundaries.

Stage transitions live in `application/transitions.py`: pure decisions select the
next stage and requested write effects. The engine keeps the single-writer lock,
source checks, checkpoints and file operations; `execute_task` is still one large
function and remains the main refactoring target. The browser has no runtime
dependencies; Node packages are only linting and formatting tools. The runtime needs
Python 3.8+, development tools need Python 3.10+ and Node 24.19+.

The response contract lives in `core/result-schemas.json` (`schema_version` 1).
Application helpers compose prompts, bind source evidence, freeze instructions and
account for durable budgets. The engine owns requirement IDs and the actual
changed-file and check records; a model cannot claim successful execution by
returning a status alone. See [contracts](contracts.md).

## Curated instruction modules

`application/instruction-modules.json` contains Python, shell, UI, verification and
decomposition guidance. Selection uses validated plan paths and observed source
reads. Initial planning starts with general verification guidance; later attempts
and stages add matching language modules. Four or more proposed change files select
decomposition guidance for planning and plan review.

The catalog is frozen in `00-input/modules.json`. Each stage records selected IDs,
module versions and text hashes; the UI shows them with instruction provenance.
Continuation rejects a missing or modified frozen catalog, so updating the
application does not change a running task. Modules grant no tools or permissions,
and no global skill loading is enabled.

Structured plan steps are local work packages. Every package owns concrete files,
criteria, dependencies and checks. Shared files or criteria require a dependency
path; identical deliverables are rejected. Independent review checks semantic
overlap and the remaining deliverable after dependencies finish. Checks and
documentation stay with their owning change. There are no parallel writers;
checkpoints keep the approved ordered plan, and an interrupted writer inspects
current files before it continues.

The optional SSH executor owns its private credentials and queue under a separate
OS user. The application submits requests through a Unix socket; only a root peer
can approve the exact digest. The executor runs nothing locally. See
[SSH executor](ssh-executor.md).
