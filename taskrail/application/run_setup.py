"""Create a run directory or reopen an interrupted one before taking the lock."""

import json
import os
import time
from pathlib import Path

from taskrail.application import (
    check_configuration,
    child_inputs,
    execution_context,
    inherited_settings,
    original_checkout,
    run_state,
    run_store,
    worktree_followup,
)
from taskrail.application.artifacts import save_run
from taskrail.application.checkpoints import RESUMABLE
from taskrail.application.task_config import configuration
from taskrail.application.worktree_isolation import isolate
from taskrail.core.files import atomic_json, atomic_write
from taskrail.observability.progress import say

INPUTS = "00-input"
RUN_INDEX = "run.json"
STATUS = "status"
ROOTS = "roots"
WORKTREES = "worktrees"
RUN_DIRECTORY = "run_dir"
SETTINGS_SNAPSHOT = (
    "opencode_version",
    "models",
    "timeout",
    "transport_retries",
    "max_integration_corrections",
    "model_context_tokens",
    "context_reserve_tokens",
    "verify_commands",
    "check_recipes",
    "check_specs",
    "protected_paths",
    "host_commands",
    "sandbox_network",
)


def configure(request):
    """The configuration and run directory; nothing is created yet."""
    restored = None
    checks = None
    if request["resume"]:
        restored = stored_index(request[RUN_DIRECTORY])
        run_store.continuing(restored)
        run = Path(request[RUN_DIRECTORY]).expanduser().resolve()
        checks = inherited_settings.continued(run, restored)
        restored = restored[ROOTS]
    else:
        checks = inherited_settings.for_request(request)
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
        return [entry.get("original_source", entry["source"]) for entry in worktrees.values()]
    return list(index[ROOTS].values())


def open_state(config, run, request, ready):
    """Create or reopen the run index; worktrees are created only once the locks are held."""
    if request["resume"]:
        state = resumed_state(run, config, request)
        execution_context.restore(run, config, state)
        return state
    if ready:
        parent = execution_context.submission_source(config, run)
        isolate(config, run.name)
        if parent is not None:
            worktree_followup.transfer(config, parent)
    state = new_state(run, config, request)
    original_checkout.capture(run, config)
    return state


def stored_index(location):
    """The run index of an existing run directory."""
    index = Path(location).expanduser().resolve() / RUN_INDEX
    return run_store.validate(json.loads(index.read_text()))


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
    state = run_store.read(run)
    run_store.continuing(state)
    if state[STATUS] not in RESUMABLE:
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
    state = execution_context.capture(
        run, config, check_configuration.capture(config, run_state.initial_state(config))
    )
    child_inputs.capture(config["task"], inputs, state)
    atomic_json(inputs / "settings.json", {key: config[key] for key in SETTINGS_SNAPSHOT})
    save_run(run, state)
    say(f"Run: {run}")
    return state
