"""Select declared local checks and retain every mandatory settings command."""

from pathlib import Path

from taskrail.application import check_recipes, check_specs, step_checks
from taskrail.core.schema import require
from taskrail.executor import protocol

CWD = "cwd"
RECIPE = "recipe"


def applicable(workflow):
    """The same effective commands decide scheduling and execution."""
    checks = assigned(workflow.config, workflow.state["requirements"])
    bound = {check["spec"].get("recipe_id") for check in checks}
    for gate in step_checks.selected(workflow.config):
        if gate["spec"]["recipe_id"] not in bound:
            checks.append(gate)
    covered = {protocol.fingerprint(check["recipe"]["request"]) for check in checks}
    for command in workflow.config.get("verify_commands", []):
        if protocol.fingerprint(command) not in covered:
            checks.append(legacy(command))
    return mapped_checks(checks, command_roots(workflow.config))


def command_roots(config):
    """Map configured source directories to the authenticated effective worktrees."""
    roots = [str(root) for root in config["roots"].values()]
    locations = {root: root for root in roots}
    for entry in config.get("worktrees", {}).values():
        locations[entry["source"]] = entry["worktree"]
    return locations


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
    location = mapped_directory(command[CWD], locations)
    if location is None:
        if check["spec"]["criteria"] or check.get("required"):
            raise ValueError("Selected check cwd is outside the declared roots")
        return None
    recipe = dict(check[RECIPE])
    recipe["request"] = dict(command, cwd=location)
    check[RECIPE] = recipe
    return check


def mapped_directory(cwd, locations):
    """Keep descendant checks within their source and effective roots, including symlinks."""
    directory = Path(cwd)
    roots = [
        Path(root)
        for root in locations
        if directory.is_relative_to(root)
        or directory.resolve().is_relative_to(Path(root).resolve())
    ]
    if not roots:
        return None
    source = max(roots, key=lambda path: len(path.parts))
    require(directory.resolve().is_relative_to(source.resolve()), "Check cwd escapes source root")
    effective = Path(locations[str(source)]).resolve()
    target = (effective / directory.resolve().relative_to(source.resolve())).resolve()
    require(target.is_relative_to(effective), "Check cwd escapes effective root")
    return str(target)
