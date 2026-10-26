"""Small model-facing catalog; execution recipes remain server-owned."""

KIND = "kind"
PHASE = "phase"


def public_catalog(catalog):
    """Advertise safe selection metadata without command arguments or embedded credentials."""
    entries = []
    for name, recipe in sorted(catalog.items()):
        entry = {key: recipe[key] for key in (KIND, PHASE, "adapter")}
        entry.update(id=name, description=recipe.get("description") or name)
        entries.append(entry)
    return entries


def context(config, stage, plan):
    """Planning sees configured bindings; independent review sees only relevant recipes."""
    if stage not in {"planner", "plan-reviewer"}:
        return {}
    checks = configured_checks(config)
    catalog = config.get("check_recipes", {})
    if stage == "plan-reviewer":
        selections = (plan or {}).get("check_selections", [])
        catalog = selected_catalog(catalog, checks + selections)
    return dict(check_catalog=public_catalog(catalog), configured_checks=checks)


def configured_checks(config):
    """Retain criterion bindings without repeating empty parameters or recipe details."""
    checks = []
    fields = ("id", "recipe_id", "criteria")
    for spec in config.get("check_specs", []):
        checks.append({key: spec[key] for key in fields})
    return checks


def selected_catalog(catalog, selections):
    """A reviewer needs selected and preconfigured recipe metadata, not unrelated choices."""
    names = {entry["recipe_id"] for entry in selections}
    return {name: recipe for name, recipe in catalog.items() if name in names}
