# Taskrail

[![CI on master](https://github.com/osipovgit/Taskrail/actions/workflows/ci.yml/badge.svg?branch=master&event=push)](https://github.com/osipovgit/Taskrail/actions/workflows/ci.yml?query=branch%3Amaster+event%3Apush)

Give [opencode](https://opencode.ai) a goal and a Git repository. Taskrail turns the goal into a plan, runs the work on an isolated branch, and gives you the reviewed change with its diff, commits and check results. Follow each step in a local browser or use the CLI.

| Choose a mode | What you get |
| --- | --- |
| **Develop** | A reviewed change on a task branch. Larger changes can split into tasks with their own checks and commits. |
| **Answer only** | An independently reviewed answer grounded in project files and recorded evidence. |
| **Design discussion** | A reviewed design document. Start a Develop follow-up when you want to implement it. |

## Run your first task

On Linux, install Git, Python 3.10+ with venv and a working opencode 1.x or 2.x on your PATH. The managed installer also uses user systemd, Bash and flock. Run it as your normal user from a trusted checkout or extracted release.

```sh
bash deploy/install.sh
```

1. Open [the local dashboard](http://127.0.0.1:8787) and choose **New task**.
2. Select the root of a Git repository with at least one commit. Describe the goal and how you will know it is done.
3. Open a stage to inspect the plan, review findings and command output. When a change is ready, inspect the diff and commits on `taskrail/<run>`. You decide when to merge.

For a first read-only run, try **Answer only** with “Where does this project validate its configuration, and which tests cover invalid input?”

The bundled settings use opencode's configured default model. For role-specific models, foreground installation, updates or a remote host, see the [deployment guide](docs/deployment.md).

## How a change reaches review

- **Understand and plan.** Taskrail extracts requirements from the original text. A planner explores the project, and a separate reviewer checks the proposed tasks against those requirements.
- **Implement and verify.** Each writer works in a linked Git worktree. Taskrail records what changed, which checks ran and their results. Review findings return to the writer. A stopped stage can resume from an eligible checkpoint with your clarification.
- **Deliver.** After result review, the server commits the approved changes. A split also receives an integration review. Optional Jenkins validation and post-confirmation server checks use the configured executor.

Local commands normally run in a sandbox where available. Commands that require host execution run under your account and are highlighted in the log. Set `host_commands` to `"ask"` to review host requests. Git pushes require a personal decision. [Access and approvals](docs/access.md)

## From the CLI

```sh
taskrail submit --root shop=/srv/shop --goal @goal.md
taskrail status RUN
taskrail action RUN resume --note "The test dependency is installed."
```

Use the run ID returned by `submit` in place of `RUN`. To run a Markdown task in the foreground, use `taskrail /absolute/path/task.md`. [CLI and run controls](docs/task-controls.md#automation-from-the-cli)

## Guides

| I want to… | Start here |
| --- | --- |
| Write a task and choose its scope | [Task format](docs/task-format.md) · [Examples](examples/live) |
| Set up tests, linters or a remote check | [Verification](docs/checks.md) · [SSH and Jenkins](docs/ssh-executor.md) |
| Inspect a branch or recover a run | [Git access](docs/git-access.md) · [Monitoring and diagnostics](docs/monitoring.md) |
| Understand or contribute to Taskrail | [Architecture](docs/architecture.md) · [Agent contracts](docs/contracts.md) · [Contributing](CONTRIBUTING.md) |

[Apache License 2.0](LICENSE) · [Report a security issue privately](SECURITY.md)
