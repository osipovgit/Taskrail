"""Checks that run after a code change: Jenkins validation and, once confirmed, server checks.

The approved plan writes them under `## After the change` with the prefixes "Jenkins check:"
and "Server check:"; runtime requirements that no selected recipe checks are server checks
too. Selected recipes stay typed check_specs and are shown by their IDs.
"""

import json
import re
from types import MappingProxyType

from taskrail.web.history import read_artifact

PREFIX = re.compile(r"\s*(jenkins|server)\s+check\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)
KINDS = MappingProxyType({"validation": "jenkins", "server": "server"})
SPECS = "check_specs"


def checks(run, state):
    """{"jenkins": [...], "server": [...]}: the written checks, then the selected recipes."""
    found = written(run, state)
    for spec in state.get(SPECS, []):
        kind = KINDS.get(spec["phase"])
        if kind:
            found[kind].append("{id}: {recipe_id}".format(**spec))
    return found


def written(run, state):
    """Checks the plan wrote and runtime requirements without a selected recipe."""
    found = dict(jenkins=[], server=[])
    for entry in planned(run, state):
        match = PREFIX.fullmatch(entry)
        if match:
            kind, check = match.groups()
            found[kind.lower()].append(check.strip())
    found["server"].extend(runtime_checks(state))
    return found


def runtime_checks(state):
    """Deferred runtime checks no selected recipe checks; they need the servers to verify."""
    bound = {criterion for spec in state.get(SPECS, []) for criterion in spec["criteria"]}
    requirements = state.get("requirements", [])
    return [
        requirement["text"]
        for requirement in requirements
        if requirement["kind"] == "runtime" and requirement["id"] not in bound
    ]


def planned(run, state):
    """The unverified entries of the approved plan, if the run has one."""
    reference = state.get("results", {}).get("plan")
    if not reference:
        return []
    return json.loads(read_artifact(run, reference)).get("unverified", [])
