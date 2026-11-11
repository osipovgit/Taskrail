"""Freeze execution recipes independently of model settings and resume budgets."""

import json

from taskrail.application import reviewed_artifacts
from taskrail.core import protected_paths
from taskrail.core.files import atomic_json, digest
from taskrail.core.schema import require

RECIPES = "check_recipes"
FIELDS = (RECIPES, "verify_commands")
SIGNATURE = "check_config_sha256"


def fingerprint(config):
    """A recipe change requires a new run and fresh approval, not a continuation."""
    settings = dict(check_recipes={}, verify_commands=[])
    for name in FIELDS:
        settings[name] = config.get(name, settings[name])
    return digest(json.dumps(settings, sort_keys=True).encode())


def capture(config, state):
    """Bind the frozen execution settings before any stage starts."""
    state[SIGNATURE] = fingerprint(config)
    return state


def restore(config, run, state):
    """Historical runs may reuse only recipes present in their saved settings.

    Protected paths frozen at the start stay protected; new settings can add more.
    """
    saved = frozen(run, state)
    inherit(config, saved)
    protected = config.get(protected_paths.KEY, [])
    config[protected_paths.KEY] = protected_paths.resumed(
        protected, saved.get(protected_paths.KEY, [])
    )
    require("check_specs" in state, "Missing selected checks in run index")
    config["check_specs"] = state["check_specs"]
    config["required_local_checks"] = state.get("required_local_checks", [])


def frozen(run, state):
    """Authenticate the stored catalog before using commands from another run."""
    expected = state.get(SIGNATURE)
    require(expected is not None, "Missing check settings seal")
    saved = reviewed_artifacts.document(run, "00-input/settings.json")
    require(isinstance(saved, dict), "Invalid frozen check settings")
    require(fingerprint(saved) == expected, "Frozen check settings changed")
    return saved


def inherit(config, saved):
    """Copy exact execution settings without replacing scoped criterion bindings."""
    config[RECIPES] = saved.get(RECIPES, {})
    config["verify_commands"] = saved.get("verify_commands", [])


def adopt(workflow, parent, state):
    """An authenticated child freezes its parent's catalog before any execution."""
    inherited = frozen(parent, state)
    inherit(workflow.config, inherited)
    path = workflow.run / "00-input/settings.json"
    saved = frozen(workflow.run, workflow.state)
    inherit(saved, inherited)
    atomic_json(path, saved)
    capture(workflow.config, workflow.state)
