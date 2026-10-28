"""Create a run directory or reopen an interrupted one before taking the lock."""

import json
import os
import time
from pathlib import Path

from taskrail.application import check_configuration, child_inputs, run_state
from taskrail.application.artifacts import save_run
from taskrail.application.checkpoints import RESUMABLE, budget_paused
from taskrail.application.task_config import configuration
from taskrail.application.worktree_isolation import adopt, isolate
from taskrail.core.files import atomic_json
from taskrail.infrastructure.agent_sync import atomic_write
from taskrail.observability.progress import say

INPUTS = "00-input"
RUN_INDEX = "run.json"
STATUS = "status"
ROOTS = "roots"
WORKTREES = "worktrees"
TOKENS = "max_observed_tokens"
RUN_DIRECTORY = "run_dir"
SETTINGS_SNAPSHOT = (
    "opencode_version",
    "models",
    "timeout",
    "stage_seconds",
    "stage_attempts",
    "read_retries",
    "stop_on_provider_limit",
    "max_repairs",
    TOKENS,
    "model_context_tokens",
    "context_reserve_tokens",
    "verify_commands",
    "check_recipes",
    "check_specs",
    "isolation",
    "max_change_lines",
    "max_change_files",
    "protected_paths",
)


def configure(request):
    """The configuration and run directory; nothing is created yet."""
    restored = None
    checks = None
    if request["resume"]:
        restored = stored_index(request[RUN_DIRECTORY])
        run = Path(request[RUN_DIRECTORY]).expanduser().resolve()
        checks = check_configuration.frozen(run, restored)
        restored = restored[ROOTS]
    config = configuration(
        request["task"], request["settings"], roots_override=restored, checks_override=checks
    )
    return config, run_directory(request[RUN_DIRECTORY], config)


def source_roots(config, request):
    """The project roots to lock; an isolated run locks the sources of its worktrees."""
    if not request["resume"]:
        return list(config[ROOTS].values())
    index = stored_index(request[RUN_DIRECTORY])
    worktrees = index.get(WORKTREES) or {}
    if worktrees:
        return [entry["source"] for entry in worktrees.values()]
    return list(index[ROOTS].values())


def open_state(config, run, request, ready):
    """Create or reopen the run index; worktrees are created only once the locks are held."""
    if request["resume"]:
        state = resumed_state(run, config, request)
        if state.get(WORKTREES):
            adopt(config, state[WORKTREES])
        return state
    if ready:
        isolate(config, run.name)
    return new_state(run, config, request)


def stored_index(location):
    """The run index of an existing run directory."""
    index = Path(location).expanduser().resolve() / RUN_INDEX
    return json.loads(index.read_text())


def run_directory(location, config):
    """Run logs live outside every source root."""
    if location:
        run = Path(location).expanduser().resolve()
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = "-".join((stamp, os.urandom(4).hex()))
        run = config["run_base"] / name
    if any(run.is_relative_to(root) for root in config[ROOTS].values()):
        raise ValueError("Run logs must be outside source roots")
    return run


def resumed_state(run, config, request):
    """Only interrupted or budget-paused runs over the same roots can continue."""
    if request["plan_response"]:
        raise ValueError("Cannot combine resume with plan import")
    state = json.loads(run.joinpath(RUN_INDEX).read_text())
    if state[STATUS] not in RESUMABLE and not budget_paused(state):
        raise ValueError("This run is not interrupted; use Restart instead")
    if state[ROOTS] != run_state.stored_roots(config[ROOTS]):
        raise ValueError("Project roots changed; cannot continue")
    check_configuration.restore(config, run, state)
    return state


def new_state(run, config, request):
    """Freeze the task, any imported draft and effective settings in 00-input."""
    seed = request["plan_response"]
    imported = Path(seed).expanduser().read_text(encoding="utf-8") if seed else None
    run.mkdir(parents=True, exist_ok=False)
    inputs = run / INPUTS
    inputs.mkdir()
    atomic_write(inputs / "task.md", config["task_text"].encode())
    if imported is not None:
        atomic_write(inputs / "imported-response.raw.txt", imported.encode())
    state = check_configuration.capture(config, run_state.initial_state(config))
    child_inputs.capture(config["task"], inputs, state)
    atomic_json(inputs / "settings.json", {key: config[key] for key in SETTINGS_SNAPSHOT})
    save_run(run, state)
    say(f"Run: {run}")
    return state
