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
    found = dict(jenkins=[], server=[])
    for entry in planned(run, state):
        match = PREFIX.fullmatch(entry)
        if match:
            kind, check = match.groups()
            found[kind.lower()].append(check.strip())
    found["server"].extend(runtime_checks(state))
    return found


def runtime_checks(state):
    """The task's deferred runtime checks, which need the servers to verify."""
    requirements = state.get("requirements", [])
    return [requirement["text"] for requirement in requirements if requirement["kind"] == "runtime"]


def planned(run, state):
    """The unverified entries of the approved plan, if the run has one."""
    reference = state.get("results", {}).get("plan")
    if not reference:
        return []
    return json.loads(read_artifact(run, reference)).get("unverified", [])
