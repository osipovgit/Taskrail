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
| `infrastructure/` | opencode launch (1.x direct, 2.x through an adapter), process watch, JSONL event summary, permission profiles |
| `observability/` | Public progress, usage and compaction telemetry |
| `executor/` | Separate system service: peer-authenticated socket, immutable tickets, root-only approval, SSH transport, Jenkins client |
| `web/server.py`, `http_handler.py`, `http_policy.py` | Loopback HTTP API, request checks and static resources |
| `web/run_view.py`, `run_list.py`, `run_files.py`, `run_messages.py`, `run_sources.py` | Bounded, contained run views for the dashboard |
| `web/service.py`, `health.py` | Managed process lifecycle and bounded readiness check |
| `web/submissions.py`, `worker.py` | Validated task creation and detached workflow launch |
| `web/history.py`, `requests.py`, `lifecycle.py` | Editable task drafts, conversation history and lifecycle controls |
| `web/static/` | Browser JavaScript, CSS, HTML and theme handling |
| `deploy/` | Offline release installation, CLI wrapper and systemd units |
| `countersign/agents/`, `countersign/settings.json` | Bundled role templates (frozen per run) and default settings |
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
run locks enforce task boundaries. Each run locks its source projects (an isolated
run locks the sources of its worktrees) and its run directory, so one project runs
one task at a time while different projects run in parallel. Managed opencode
profiles carry a per-run suffix, so parallel runs never share permissions.

Stage transitions live in `application/transitions.py`: pure decisions select the
next stage and requested write effects. The engine keeps the project locks,
source checks, checkpoints and file operations:

| Module (`application/`) | Responsibility |
|---|---|
| `workflow_engine.py` | Lock, stage loop, transitions and write effects |
| `run_setup.py`, `run_state.py`, `task_config.py`, `task_roots.py` | Run directory, frozen inputs and validated configuration |
| `worktree_isolation.py` | Optional linked Git worktree per root and run |
| `workflow_start.py`, `workflow_finish.py` | Fresh start or checkpoint continuation; interruption and the final report |
| `workflow_state.py`, `source_guard.py` | Run state, flow, checkpoints and source/Git integrity |
| `stage_attempts.py`, `attempt_*.py` | One model stage: profile, launch, validation and bounded retries |
| `check_stage.py`, `builtin_checks.py`, `verify_*.py` | Syntax checks and settings verification commands |
| `source_tree.py`, `git_state.py`, `planned_paths.py`, `plan_validation.py`, `changes.py` | Fingerprints, path safety, plan checks, preimages and the diff |

The browser has no runtime
dependencies; Node packages are only linting and formatting tools. The runtime needs
Python 3.10+ for both the runtime and development tools, and Node 24.19+ for UI linting.

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
can approve the exact digest. The executor runs nothing locally. It also holds the
Jenkins API token: Jenkins reads run on request, builds are root-approved tickets. See
[SSH and Jenkins executor](ssh-executor.md).
