# Taskrail

A local, browser-first application for research, scoped code changes and independent
review through [opencode](https://opencode.ai). Code changes use isolated Git
worktrees by default in the browser; tasks can also edit declared project roots.
It preserves unrelated work and uses controlled Git access without automatic
rollback. Git history is available to all roles; task-required writes are restricted
to the implementer. CLI remains supported.

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
taskrail init          # writes ~/.config/taskrail/settings.json
taskrail check         # verifies opencode, settings and permission enforcement
taskrail serve
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

Planning as decomposition → independent plan review → scoped implementation →
built-in syntax checks and your [verification commands](docs/deployment.md#verification-commands)
→ independent result review → combined integration review after a split →
Jenkins validation, when the plan names Jenkins checks →
your confirmation → server checks, only after it. The planner writes its plan as a
Markdown file; it chooses one atomic task or splits into independent tasks, one run per task, in
dependency order ([delivery](docs/task-controls.md#delivery-of-a-code-change)).
A change larger than the configured limit waits for your decision first. A reviewed no-change plan ends without implementation; **Design
discussion** turns produce a reviewed design document instead of code.
Failed checks/review may request bounded repairs. Interrupted writers are never
replayed automatically. Partial changes remain available for inspection. A task can
run in [isolated Git worktrees](docs/task-format.md#worktree-isolation) on a new
branch, the default in the browser, leaving the source checkout untouched: there each
approved task is finalized with verified commits and may change files beyond its plan. Tasks on different projects run in
parallel; one project runs one task at a time.

A finished change waits as **Ready for your review** until you confirm it; **No
changes required** ends a run that needed no edits. Agents run project tests and
linters at once in an offline [sandbox](docs/access.md#local-commands) where the host
has bubblewrap; commands that need more, Docker, CI and deployment wait for your
approval, one by one or once per run. The optional
[isolated SSH executor](docs/ssh-executor.md) runs exact remote scripts and Jenkins builds after personal
root approval, with results returned to the same task. Deferred runtime checks
remain visible. The planner and the reviewers write Markdown files and finish with `DONE`;
the implementer finishes with `DONE` or `BLOCKED`. See the
[response contracts](docs/contracts.md). Source quotations
and per-requirement outcomes are checked before each transition.

## CLI

The CLI runs a task in the foreground, or starts and controls runs for automation
(a chat bot or script on the server) with the browser's launcher; see
[automation](docs/task-controls.md#automation-from-the-cli).

```sh
taskrail /absolute/path/task.md
taskrail submit --root shop=/srv/shop --goal @goal.md
taskrail status RUN
taskrail decide RUN allow
taskrail action RUN resume --note "python3 is installed now"
taskrail analytics
# Foreground development UI:
python3 -m taskrail serve --settings taskrail/settings.json
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

Taskrail is licensed under the [Apache License 2.0](LICENSE). Report vulnerabilities
privately as described in [SECURITY.md](SECURITY.md); see [CONTRIBUTING.md](CONTRIBUTING.md) to contribute.
Every repository task ends with an open pull request targeting `master` and a link
to it. Merging requires passing pipelines and the repository owner's personal
review. Direct commits and pushes to `master` are prohibited.
