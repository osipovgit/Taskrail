"""Checks that run after a code change: Jenkins validation and, once confirmed, server checks.

The approved plan names them in unverified with the prefixes "Jenkins check:" and
"Server check:"; the task's deferred runtime checks are server checks too.
"""

import json
import re

from countersign.web.history import read_artifact

PREFIX = re.compile(r"\s*(jenkins|server)\s+check\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)


def checks(run, state):
    """{"jenkins": [...], "server": [...]} for a run's approved plan and task."""
    found = legacy_checks(run, state)
    selected = typed(run, state)
    bound = {criterion for spec in selected for criterion in spec["criteria"]}
    found["server"].extend(runtime_checks(state, bound))
    for spec in selected:
        kind = "jenkins" if spec["phase"] == "validation" else "server"
        if spec["phase"] in {"validation", "server"}:
            found[kind].append("{id}: {recipe_id}".format(**spec))
    return found


def legacy_checks(run, state):
    """Older prose remains visible without becoming an executable recipe."""
    found = dict(jenkins=[], server=[])
    for entry in planned(run, state):
        match = PREFIX.fullmatch(entry)
        if match:
            kind, check = match.groups()
            found[kind.lower()].append(check.strip())
    return found


def runtime_checks(state, bound=()):
    """The task's deferred runtime checks, which need the servers to verify."""
    requirements = state.get("requirements", [])
    return [
        requirement["text"]
        for requirement in requirements
        if requirement["kind"] == "runtime" and requirement["id"] not in bound
    ]


def typed(run, state):
    """Canonical check references stay separate from legacy prose for older runs."""
    return state.get("check_specs", [])


def planned(run, state):
    """The unverified entries of the approved plan, if the run has one."""
    reference = state.get("results", {}).get("plan")
    if not reference:
        return []
    return json.loads(read_artifact(run, reference)).get("unverified", [])
