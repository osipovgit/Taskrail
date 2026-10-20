# Countersign

A local, browser-first application for research, scoped code changes and independent
review through [opencode](https://opencode.ai). It edits original project roots,
preserves unrelated work and uses controlled Git access without automatic rollback. Git history is available to
all roles; task-required writes are restricted to the implementer. CLI remains supported.

## Start

Requirements: Linux user systemd, Python 3.10+ with venv, bash, tar, flock and a working
opencode 1.x or 2.x installation on PATH. Install as your normal user, without sudo:

```sh
bash deploy/install.sh
# Import existing settings and custom roles only on first installation:
# bash deploy/install.sh /absolute/path/settings.json
```

Without the managed service, install the package and run the UI in the foreground:

```sh
pipx install .            # from a checkout or an extracted release
countersign init          # writes ~/.config/countersign/settings.json
countersign check         # verifies opencode, settings and permission enforcement
countersign serve
```

The bundled settings launch `opencode` with its configured default model; set role
`models` or a wrapper `command` as described in [opencode settings](docs/deployment.md#opencode).

Open http://127.0.0.1:8787 and select **New task**. Provide project roots, Goal and
acceptance criteria; let the planner discover related files. The service is local
and not intended for public or multi-user exposure.

To update from a trusted extracted release:

```sh
bash deploy/install.sh --wait=3600 --autostart=keep
```

Settings/history survive; the installer switches the release and restarts the
service. Imported custom roles are preserved, not overwritten by bundled updates.
See [deployment](docs/deployment.md) before changing existing installations.

## Workflow

Planning → independent plan review → scoped implementation → built-in syntax checks
and your [verification commands](docs/deployment.md#verification-commands) →
independent result review. A change larger than the configured limit waits for your
decision first. A reviewed no-change plan ends without implementation; **Design
discussion** turns produce a reviewed design document instead of code.
Failed checks/review may request bounded repairs. Interrupted writers are never
replayed automatically. Partial changes remain available for inspection. A task can
also run in [isolated Git worktrees](docs/task-format.md#worktree-isolation) on a new
branch, leaving the source checkout untouched. Tasks on different projects run in
parallel; one project runs one task at a time.

Success means **Ready for your review**, **No changes required** or, for a goal split
into tasks, **Tasks ready**. Other project tests, Docker, CI and deployment never run
automatically; agents may request local commands that you approve one by one or once
per run, while read-only listings inside the projects run without asking. The optional
[isolated SSH executor](docs/ssh-executor.md) runs exact remote scripts and Jenkins builds after personal
root approval, with results returned to the same task. Deferred runtime checks
remain visible. Every model result follows a strict JSON contract; source quotations
and per-requirement outcomes are checked before each transition.

## CLI

```sh
countersign /absolute/path/task.md
countersign status /absolute/path/run
countersign resume /absolute/path/run --note "python3 is installed now"
countersign analytics
# Foreground development UI:
python3 -m countersign serve --settings countersign/settings.json
```

## Guides

- [Isolated SSH and Jenkins executor and approvals](docs/ssh-executor.md)
- [Task format and example](docs/task-format.md)
- [Controls, continuation and history](docs/task-controls.md)
- [Configuration, deployment and file locations](docs/deployment.md)
- [Metrics, budgets and diagnostics](docs/monitoring.md)
- [Contracts and instruction ownership](docs/contracts.md)
- [Architecture](docs/architecture.md) · [Development](docs/development.md)

For a failure, share `run.json`, `report.md`, and the affected stage's `stage.json`,
`request.md`, `response.raw.txt`, `events.jsonl`, `stderr.log`. Include `budgets.json`
and `evidence.json` for recovery issues. Inspect source snippets and redact secrets.

For a deliberate clean reinstall use
`bash deploy/install.sh --fresh --wait=3600 --autostart=keep --agents=bundled`. It deletes
managed history and configuration; read the [reset scope](docs/deployment.md#full-reinstallation)
first. [Access routes](docs/access.md) describe what agents may read, edit and run.

## License and security

Countersign is licensed under the [Apache License 2.0](LICENSE). Report vulnerabilities
privately as described in [SECURITY.md](SECURITY.md); see [CONTRIBUTING.md](CONTRIBUTING.md) to contribute.
