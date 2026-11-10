"""Select declared local checks and retain every mandatory settings command."""

from pathlib import Path

from taskrail.application import check_recipes, check_specs, step_checks, worktree_default
from taskrail.core.schema import require
from taskrail.executor import protocol

CWD = "cwd"
RECIPE = "recipe"
REQUEST = "request"


def applicable(config, requirements):
    """Effective configured gates for this task, in execution order."""
    checks = assigned(config, requirements)
    bound = {check["spec"].get("recipe_id") for check in checks}
    for gate in step_checks.selected(config):
        if gate["spec"]["recipe_id"] not in bound:
            checks.append(gate)
    return mapped_checks(checks, config.get("verify_commands", []), command_roots(config))


def command_roots(config):
    """Map configured source directories to the authenticated effective worktrees."""
    roots = [str(root) for root in config["roots"].values()]
    locations = {root: root for root in roots}
    for entry in config.get("worktrees", {}).values():
        for origin in worktree_default.origins(entry):
            locations[str(origin)] = entry["worktree"]
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


def configured_command(command):
    """An old exact verification setting has no invented criterion association."""
    spec = dict(id=check_recipes.verification_id(command), criteria=[])
    recipe = dict(kind="local", request=command, adapter="exit-code")
    return dict(spec=spec, recipe=recipe)


def mapped_checks(checks, commands, locations):
    """Keep every explicit binding, then add each uncovered effective settings command."""
    selected = [mapped_check(check, locations) for check in checks]
    covered = {protocol.fingerprint(check[RECIPE][REQUEST]) for check in selected}
    for command in commands:
        check = mapped_check(configured_command(command), locations)
        if check is None:
            continue
        signature = protocol.fingerprint(check[RECIPE][REQUEST])
        if signature not in covered:
            covered.add(signature)
            selected.append(check)
    return selected


def mapped_check(check, locations):
    """Map source roots to worktrees before presenting the exact approval request."""
    command = check[RECIPE][REQUEST]
    location = mapped_directory(command[CWD], locations)
    if location is None:
        if check["spec"]["criteria"] or check.get("required"):
            raise ValueError("Selected check cwd is outside the declared roots")
        return None
    recipe = dict(check[RECIPE])
    recipe[REQUEST] = dict(command, cwd=location)
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
