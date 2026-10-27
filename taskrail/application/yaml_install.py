"""Offer to install PyYAML when no Python here can check the changed YAML files.

The check stage asks once per run. With pip or uv the request installs PyYAML into
Taskrail's own package directory, so this and every later run can check YAML; Allow
all actions covers it like any local command. Without an installer the operator
installs it by hand and then allows a recheck, which is always a personal decision.
After Allow the files are checked at once; after Deny they stay unchecked.
"""

import shutil
from pathlib import Path

from taskrail.application import builtin_checks, yaml_check
from taskrail.application.planned_paths import safe_file
from taskrail.interactions import approval_policy, local_actions

DECISION = "yaml_install"
MANUAL_STEP = "MANUAL_STEP"
ALLOWED = "allowed"
PACKAGE = "PyYAML"
PIP = "pip"
INSTALL_SECONDS = 600
# The uv installer puts uv here, which a service started at boot may not have on PATH.
USER_BIN = str(Path.home() / ".local" / "bin")
OUTPUT_LINES = 2
OUTPUT_TAIL = 400
REASON = "Install PyYAML so the check stage can syntax-check YAML files"
OFFER = "PyYAML is missing, so changed YAML files can't be syntax-checked. Allow installs it into {0} for this and later runs; Deny leaves them unchecked."
MANUAL = "PyYAML is missing, so changed YAML files can't be syntax-checked, and neither pip nor uv is available. Install it on this host (for example: sudo apt install python3-yaml), then Allow to check them; Deny leaves them unchecked."
DECLINED = "YAML not checked: the PyYAML install was declined"
STILL_MISSING = "YAML not checked: PyYAML is still missing after the install"


def resolve(workflow, folder, checks):
    """The checks, with unchecked YAML files checked again after an allowed install."""
    if all(check["detail"] != yaml_check.MISSING for check in checks):
        return checks
    state = workflow.state
    if DECISION not in state:
        state[DECISION] = install(workflow, folder)
    roots = workflow.config["roots"]
    return [recheck(check, roots, state[DECISION]) for check in checks]


def recheck(check, roots, outcome):
    """A YAML check after the install, or its reason to stay unchecked."""
    if check["detail"] != yaml_check.MISSING:
        return check
    if outcome != ALLOWED:
        return dict(check, detail=outcome)
    return builtin_checks.file_check(check["file"], safe_file(check["file"], roots))


def install(workflow, folder):
    """ALLOWED when PyYAML is importable after the decision, else why YAML stays unchecked."""
    command = installer()
    payload, shown = request(workflow, command)
    decision = approval_policy.decision(workflow.run, shown, workflow.state, personal=not command)
    if decision["decision"] != "allow":
        return DECLINED
    tail = run_install(workflow, folder, payload, decision) if command else ""
    yaml_check.source.cache_clear()
    if yaml_check.source():
        return ALLOWED
    return f"{STILL_MISSING}: {tail}" if tail else STILL_MISSING


def request(workflow, command):
    """The local request, if any, and what the operator reads; a manual step runs nothing."""
    if command is None:
        return None, dict(status=MANUAL_STEP, schema_version=1, reason=REASON, notice=MANUAL)
    root = next(iter(workflow.config["roots"].values()))
    payload = dict(status="LOCAL_REQUEST", schema_version=1, cwd=str(root), reason=REASON)
    payload["argv"] = command
    return payload, dict(payload, notice=OFFER.format(yaml_check.TARGET))


def run_install(workflow, folder, payload, decision):
    """Run the approved install; the last lines of its error output when it reports one."""
    context = dict(roots=workflow.config["roots"], run=workflow.run, timeout=INSTALL_SECONDS)
    outcome = local_actions.execute(workflow.run, folder, payload, context, decision)
    output = outcome.get("stderr") or outcome.get("reason") or ""
    stripped = map(str.strip, str(output).splitlines())
    lines = [line for line in stripped if line]
    return " ".join(lines[-OUTPUT_LINES:])[-OUTPUT_TAIL:]


def installer():
    """argv that installs PyYAML into Taskrail's package directory, or None."""
    target = str(yaml_check.TARGET)
    for python in yaml_check.pythons():
        if yaml_check.completed(python, "-m", PIP, "--version").returncode == 0:
            pip = [python, "-m", PIP, "install", "--disable-pip-version-check"]
            return [*pip, "--no-input", "--target", target, PACKAGE]
    uv = shutil.which("uv") or shutil.which("uv", path=USER_BIN)
    if uv is None:
        return None
    checker = yaml_check.pythons()[0]
    return [uv, PIP, "install", "--python", checker, "--target", target, PACKAGE]


def health():
    """Informational check line: how the check stage validates YAML."""
    checker = yaml_check.source()
    if checker:
        return True, f"YAML syntax checks: {checker}"
    return True, "YAML syntax checks: no PyYAML yet; the check stage offers to install it"
