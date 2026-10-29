# Architecture

The browser is the primary interaction surface, served by a managed user service.
The application has one execution engine and two entry points: CLI and HTTP
submission both invoke `application.live.execute_task`; the web worker does not
implement a second workflow. State is persisted on disk, outside project roots.
UI updates read the ordered stage index and public event stream.

| Location | Responsibility |
|---|---|
| `taskrail/cli.py`, `__main__.py` | CLI parsing and module entry point |
| `cli_api.py`, `cli_requests.py`, `cli_runs.py` | Automation commands (`submit`, `decide`, `action`, `status`) through the browser's launcher |
| `application/` | Workflow, stage artifacts, checkpoints, budgets, prompts and research recovery |
| `interactions/` | Same-session executor turns: one request parser (`request_envelope.py`), routing (`request_routes.py`, `local_route.py`), exact-command approvals, adopted command effects, active clock |
| `git/` | Controlled Git grammar, scope checks, isolated process execution and output snapshots |
| `core/` | Result contract, schema validation, the prompt text catalog (`prompt-texts.json`), requirement labels, file/path utilities and stop/read-only guards |
| `infrastructure/` | opencode launch (1.x direct, 2.x through an adapter), process watch, JSONL event summary, permission profiles, the bubblewrap sandbox of local commands (`sandbox.py`) |
| `observability/` | Public progress, usage and compaction telemetry |
| `executor/` | Separate system service: peer-authenticated socket, immutable tickets, root-only approval, SSH transport, Jenkins client |
| `web/server.py`, `http_handler.py`, `http_policy.py` | Loopback HTTP API, request checks and static resources |
| `web/run_view.py`, `run_list.py`, `run_files.py`, `run_messages.py`, `run_sources.py` | Bounded, contained run views for the dashboard |
| `web/run_family.py`, `run_attempts.py` | Task and phase runs shown in their parent's card, with every earlier attempt |
| `web/service.py`, `health.py` | Managed process lifecycle and bounded readiness check |
| `web/submissions.py`, `worker.py` | Validated task creation and detached workflow launch |
| `web/history.py`, `requests.py`, `lifecycle.py` | Editable task drafts, conversation history and lifecycle controls |
| `web/static/` | Browser JavaScript, CSS, HTML and theme handling |
| `deploy/` | Offline release installation, CLI wrapper and systemd units |
| `deployment/` | Installer helpers: first-install settings and service PATH (`settings_init.py`), validated fresh-install reset (`fresh.py`) |
| `taskrail/agents/`, `taskrail/settings.json` | Bundled role templates (frozen per run) and default settings |
| `tests/` | Automatic regressions and explicitly requested scenario acceptance tasks; see [test suites](testing.md) |
| `tools/` | Development quality gates: pinned tool versions and the Wemake run |
| `docs/`, `examples/` | Documentation and example tasks |

Dependency direction: CLI/web -> application, interactions and git (the workflow
layer) -> infrastructure/observability -> core. Core imports nothing outside core;
the executor imports only core and itself. Architecture tests enforce the core and
executor boundaries. The delivery of a split (next task, integration review, Jenkins
validation, confirmation) is driven by the managed service from `web/`; CLI automation
commands use the same launcher and records. No plugins, message bus, service container or database are used. New
entry points must call the existing workflow instead of adding an execution path.

Run artifacts: `00-input/`, numbered stage directories, `run.json`, `checkpoint.json`,
the report and the diff. Declared roots, allowed writes, Git metadata checks and the
run locks enforce task boundaries. Each run locks its run directory and its source
projects (an isolated run locks the sources of its worktrees) by canonical path, so a
symlinked alias names the same project. A project also excludes runs on its parent
directories and subdirectories, and a project inside a Git work tree excludes every
other run in that repository, including runs in its linked worktrees: they share an
index or the refs the integrity guard watches. Independent projects run in parallel.
Managed opencode profiles carry a per-run suffix, so parallel runs never share
permissions.

Stage transitions live in `application/transitions.py`: pure decisions select the
next stage and requested write effects. The engine keeps the project locks,
source checks, checkpoints and file operations:

| Module (`application/`) | Responsibility |
|---|---|
| `workflow_engine.py` | Lock, stage loop, transitions and write effects |
| `run_setup.py`, `run_state.py`, `task_config.py`, `task_roots.py` | Run directory, frozen inputs and validated configuration |
| `worktree_isolation.py`, `worktree_default.py` | Linked Git worktree per root and run, by default for code changes in repositories |
| `workflow_start.py`, `workflow_finish.py` | Fresh start or checkpoint continuation; interruption and the final report |
| `workflow_state.py`, `source_guard.py`, `source_ignores.py` | Run state, flow, checkpoints and source/Git integrity; Git-ignored files are not source |
| `prompts.py`, `policy_sections.py`, `mode_rules.py`, `response_format.py` | The request of a stage from frozen policy sections and catalog texts |
| `reviewed_start.py`, `reviewed_sources.py`, `outside_changes.py`, `child_brief.py`, `previous_attempt.py` | A split task started from the reviewed plan: attempt chain, changes made outside the tasks, brief and retries |
| `integration_changes.py`, `inherited_preimages.py` | The combined diff a split's integration review reads |
| `stage_attempts.py`, `attempt_*.py` | One model stage: profile, launch, validation and bounded retries |
| `check_stage.py`, `builtin_checks.py`, `verify_*.py` | Syntax checks and settings verification commands |
| `source_tree.py`, `git_state.py`, `planned_paths.py`, `plan_validation.py`, `changes.py` | Fingerprints, path safety, plan checks, preimages and the diff |

The browser has no runtime
dependencies; Node packages are only linting and formatting tools. The runtime needs
Python 3.10+ for both the runtime and development tools, and Node 24.19+ for UI linting.

Models write no JSON results: the server reads `plan.md`, `review.md` and the
implementer's final `DONE` or `BLOCKED` and stores canonical version 1 records
(`core/plan_document.py`, `core/review_document.py`). `core/result-schemas.json` holds
the planner's stored shape and the executor request contracts. A run
frozen with other schemas stays viewable, but Continue refuses it; use Restart.
Application helpers compose prompts, bind source evidence, freeze instructions and
account for durable budgets. The engine owns requirement IDs and the actual
changed-file and check records; a model cannot claim successful execution by
returning a status alone. See [contracts](contracts.md).

## Curated instruction modules

`application/instruction-modules.json` selects reading, Python, shell, UI and
verification modules by metadata and catalog key; their prose lives in
`core/prompt-texts.json`. Every stage gets the reading module, which
keeps large inputs within the model context: search first, map a large file by its
landmarks, read windows of at most 200 lines, never re-read a range, and map diffs
and long outputs before reading them. Selection of the others uses validated plan
paths and observed source reads. Initial planning starts with general verification
guidance; later attempts and stages add matching language modules. The decomposition
rules belong to the run's mode rule (`application/mode_rules.py`).

The catalog is frozen in `00-input/modules.json`. Each stage records selected IDs,
module versions and text hashes; the UI shows them with instruction provenance.
Continuation rejects a missing or modified frozen catalog, so updating the
application does not change a running task. Modules grant no tools or permissions,
and no global skill loading is enabled.

Plan tasks form a dependency graph (`core/task_graph.py`): the server rejects unknown,
self and cyclic dependencies, runs tasks in topological order (plan order breaks
ties) and gives reviewers that order. Every task owns concrete files, requirements
or scoped parts of them, results and checks; tasks sharing a file require an explicit dependency chain and distinct behavior. Independent review checks semantic overlap and the
remaining deliverable after dependencies finish. There are no parallel writers;
checkpoints keep the approved plan, and an interrupted writer inspects current files
before it continues.

Child task headers carry the parent's immutable file scope; no nested split can reach
implementation. On a `taskrail/` branch (`task_branch.py`) the plan's files are the
expected scope: changes beyond them are adopted with preimages from the branch's last
commit and judged by review, and each approved task is committed (`task_commit.py`). The server authenticates the reviewed plan digest,
requirement lineage and accepted prerequisite results before starting a child directly
at implementation, and names the files changed outside the split's tasks along the
attempt chain; a child of an unsealed parent is refused.
A bounded prerequisite index points to a sealed full parent snapshot. After all children finish, a read-only integration run reviews
the complete original goal and criteria through the same execution engine and
independent reviewer. Standalone and split confirmation use the same reviewed
source/Git checkpoint and freeze the accepted completion and result artifacts.
Phase launch, adoption and server execution recheck that snapshot; drift requires
another review and confirmation. Revoking Allow all also marks already linked and
not-yet-created family workers, so an older child cannot retain a stale grant.

Controlled history writes record the committed source baseline for later staging
without changing the immutable original preimages. User-staged content and unrelated
pre-existing source edits never become the run's staging authority.

Before the first planning request the server writes `00-input/project-map.md`
(`application/project_map.py`): an index, every source file of each root with its line
count and landmarks (YAML task names and keys; definitions in Python, shell, JavaScript,
TypeScript, Java, Go and Groovy; Jenkins stages; Dockerfile `FROM`/`ENTRYPOINT`/`CMD`;
Terraform blocks; Jinja2 blocks and macros; Markdown headings), and for every
requirement the first lines that name its distinctive words. Long command output also
comes with a digest of its severities, most mentioned files and rules
(`interactions/output_digest.py`). Response schemas are compact JSON, one alternative
per line. SSH and Jenkins schemas use the same available targets/jobs and stage
permissions as their instructions (`application/response_format.py`); an absent,
unreachable or empty executor advertises neither capability. All roles run with automatic compaction disabled. Admission measures each role's
request, frozen role and approved source inputs against the configured context
capacity and reserve; usage monitoring separately checks provider input including
cache and explicit compaction events. A session ends at a boundary between 90 and 95
percent of its model's window; the next attempt starts a fresh session instead of
compacting. Read-only recovery starts it from recorded evidence while retaining the
plan file; a writer continues from its kept edits and `progress.md`, never after
any other interruption. Every turn of a stage runs on one private opencode server
(`opencode_serve.py` for 1.x, the adapter for 2.x), so reads of earlier turns stay
known and turns start warm. See [context limits](deployment.md#context-limits).

The optional SSH executor owns its private credentials and queue under a separate
OS user. The application submits requests through a Unix socket; only a root peer
can approve the exact digest. The executor runs nothing locally. It also holds the
Jenkins API token: reads run on request; builds need root approval unless root has
preauthorized that job with `approval: none`. See
[SSH and Jenkins executor](ssh-executor.md).
