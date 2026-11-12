"""Executable Verify bullets from the independently approved task, using the local check runner."""

import json
import re
from pathlib import Path

from taskrail.application import check_expectations, reviewed_artifacts, verify_settings
from taskrail.core import prompt_texts, schema
from taskrail.core.files import digest
from taskrail.core.plan_keys import RUN_COMMAND
from taskrail.executor import protocol
from taskrail.interactions import local_policy

ARGV = "argv"
ROOT = "root"
IDENTITY_LENGTH = 16
NUMERIC_EXIT = re.compile(
    r"\bexits?(?:[ _-](?:code|status))?(?:\s+|\s*[:=]\s*)`?\d+\b", re.IGNORECASE
)
REQUIRED = frozenset((ROOT, ARGV))
ALLOWED = REQUIRED | {"cwd", "expect"}


def approved(workflow):
    """Read the sealed plan from disk. A checkpoint or an implementation message cannot add commands."""
    reference = workflow.state.get("results", {}).get("plan")
    if not reference:
        return []
    encoded = reviewed_artifacts.read(workflow.run, reference)
    seal = workflow.state.get(reviewed_artifacts.SEAL)
    if seal:
        schema.require(digest(encoded) == seal, "Reviewed plan changed before verification")
    commands = entries(json.loads(encoded), workflow.config["roots"])
    schema.require(not commands or seal, "Unsealed verification commands")
    return commands


def entries(plan, roots):
    """Only an explicit JSON run bullet schedules work. Prose remains review guidance."""
    checks = {}
    for step in plan.get("steps", []):
        for check in step_commands(step, roots):
            checks[check["spec"]["id"]] = check
    return list(checks.values())


def step_commands(step, roots):
    """An explicit exit assertion cannot silently become a manual observation."""
    for instruction in step.get("checks", []):
        prefix = instruction.lower()
        if prefix.startswith(RUN_COMMAND):
            yield parse(instruction[len(RUN_COMMAND) :], roots)
        elif not prefix.startswith("manual:") and NUMERIC_EXIT.search(instruction):
            raise ValueError(prompt_texts.text("validation.verify_exit", task=step["id"]))


def parse(text, roots):
    """The executable, its working directory and result assertions are reviewed together."""
    fields = json.loads(text, object_pairs_hook=schema.unique_fields)
    schema.require(
        isinstance(fields, dict) and REQUIRED <= fields.keys() <= ALLOWED,
        "Verify run needs root, argv and optional cwd and expect",
    )
    command = dict(cwd=directory(fields, roots), argv=fields[ARGV])
    return gate(verify_settings.parse_command(command), fields.get("expect", {}))


def gate(request, expect):
    local_policy.read_only(request[ARGV])
    schema.require(
        not local_policy.inline_script(request[ARGV]),
        "Verify run needs the checked program's argv. Split inline shell commands into separate checks.",
    )
    recipe = dict(
        request=request,
        adapter="exit-code",
        expect=check_expectations.validate(expect),
    )
    identity = protocol.fingerprint(recipe)[:IDENTITY_LENGTH]
    spec = dict(id=f"plan-{identity}", criteria=[])
    return dict(spec=spec, recipe=recipe, required=True)


def directory(fields, roots):
    """Resolve a relative directory under its named effective worktree."""
    alias = fields[ROOT]
    schema.require(isinstance(alias, str) and alias in roots, "Unknown Verify run root")
    name = fields.get("cwd", ".")
    schema.require(
        isinstance(name, str) and bool(name), "Verify run cwd must be a relative directory"
    )
    root = Path(roots[alias])
    relative = Path(name)
    schema.require(
        not relative.is_absolute() and ".." not in relative.parts, "Verify run cwd escapes root"
    )
    target = root / relative
    schema.require(target.resolve() == target, "Verify run cwd is not canonical")
    return str(target)
