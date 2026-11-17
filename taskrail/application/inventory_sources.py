"""Protect task-named Ansible credentials before capturing files or starting a model."""

import re
from pathlib import Path

from taskrail.application import (
    inventory_credentials,
    inventory_inputs,
    project_files,
    workspace_paths,
)
from taskrail.executor import inventory

# Absolute and root-relative YAML paths in prose, including quoted paths with spaces.
YAML_PATH = re.compile(r"[`\"']([^`\"'\n]+?\.ya?ml)[`\"']|([\w./@+=~-]+\.ya?ml)\b")
ABSOLUTE_YAML = r"{root}/[^\n`\"']*?\.ya?ml\b"


def named(config):
    fields = config.get("task_spec", {}).get("fields", [])
    prose = "\n".join(field["text"] for field in fields)
    found = set()
    inputs = tuple(map(Path, config.get(inventory_inputs.KEY, [])))
    for copies in checkouts(config):
        found.update(map(mask, protected(copies, prose, inputs)))
        found.update(companions(copies, inputs))
    return sorted(found)


def checkouts(config):
    mapping = workspace_paths.mappings(config)
    for root in config["roots"].values():
        copies = {source for source, target in mapping if target == root}
        yield copies.union((Path(root),))


def protected(copies, prose, inputs):
    names = set()
    for root in copies:
        names.update(path.relative_to(root) for path in candidates(root, prose))
        names.update(inventory_inputs.files(root, inputs))
    for root in copies:
        yield from inventory_credentials.hidden(root, names)


def companions(copies, inputs):
    for root, source in inventory_inputs.locations(copies, inputs):
        directory = source if source.is_dir() else source.parent
        for name in ("host_vars", "group_vars"):
            path = directory / name
            if path.is_dir():
                yield f"{mask(path.relative_to(root))}/*"


def mask(relative):
    """Use the longest literal suffix both permission matchers can represent safely."""
    parts = []
    for part in reversed(relative.parts):
        if re.search(r"[\[\]*?\\\r\n]", part):
            break
        parts.append(part)
    return "/".join(reversed(parts))


def candidates(root, prose):
    if ".yml" not in prose and ".yaml" not in prose:
        return
    # Include literal absolute paths with spaces even when the user didn't quote them.
    absolute = ABSOLUTE_YAML.format(root=re.escape(str(root)))
    names = set(re.findall(absolute, prose))
    for quoted, plain in YAML_PATH.findall(prose):
        names.add(quoted or plain)
    for path in project_paths(root, names):
        if (
            root in path.parents
            and ".." not in path.parts
            and inventory.NAME_PATTERN.fullmatch(path.name)
        ):
            yield path


def project_paths(root, names):
    yield from (root / name for name in names)
    basenames = {name for name in names if Path(name).name == name}
    if basenames:
        for relative in project_files.listing(root):
            if Path(relative).name in basenames:
                yield root / relative
