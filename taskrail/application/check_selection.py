"""Select declared local checks and retain every mandatory settings command."""

from taskrail.application import check_recipes, check_specs
from taskrail.executor import protocol

CWD = "cwd"
RECIPE = "recipe"


def selected(workflow):
    """Explicit checks replace only identical commands, never required gates."""
    checks = assigned(workflow.config, workflow.state["requirements"])
    covered = {protocol.fingerprint(check["recipe"]["request"]) for check in checks}
    for command in workflow.config["verify_commands"]:
        if protocol.fingerprint(command) not in covered:
            checks.append(legacy(command))
    return checks


def assigned(config, requirements):
    """Only this phase's references are selected, in their declared order."""
    specs = check_specs.configured(config, requirements)
    recipes = config.get("check_recipes", {})
    return [
        dict(spec=spec, recipe=recipes[spec["recipe_id"]])
        for spec in specs
        if spec["phase"] == "check"
    ]


def legacy(command):
    """An old exact verification setting has no invented criterion association."""
    spec = dict(id=check_recipes.verification_id(command), criteria=[])
    recipe = dict(kind="local", request=command, adapter="exit-code")
    return dict(spec=spec, recipe=recipe)


def mapped_checks(checks, locations):
    """Only legacy settings may silently target another project."""
    selected = []
    for check in checks:
        mapped = mapped_check(check, locations)
        if mapped is not None:
            selected.append(mapped)
    return selected


def mapped_check(check, locations):
    """Map source roots to worktrees before presenting the exact approval request."""
    command = check[RECIPE]["request"]
    location = locations.get(command[CWD])
    if location is None:
        if check["spec"]["criteria"]:
            raise ValueError("Selected check cwd is outside the declared roots")
        return None
    recipe = dict(check[RECIPE])
    recipe["request"] = dict(command, cwd=location)
    check[RECIPE] = recipe
    return check
