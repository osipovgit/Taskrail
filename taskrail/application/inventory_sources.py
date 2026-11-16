"""Protect task-named Ansible credentials before capturing files or starting a model."""

import re
from pathlib import Path

from taskrail.application import project_files
from taskrail.executor import inventory, inventory_file, inventory_groups

# Absolute and root-relative YAML paths in prose, including quoted paths with spaces.
YAML_PATH = re.compile(r"[`\"']([^`\"'\n]+?\.ya?ml)[`\"']|([\w./@+=~-]+\.ya?ml)\b")
PASSWORD_FIELDS = tuple(name.encode() for name in inventory_groups.CONNECTION["password"])
ABSOLUTE_YAML = r"{root}/[^\n`\"']*?\.ya?ml\b"
ESCAPED_KEY = re.compile(rb"\\(?:[xuU]|[\r\n])")


def named(config):
    fields = config.get("task_spec", {}).get("fields", [])
    prose = "\n".join(field["text"] for field in fields)
    found = set()
    for root in map(Path, config["roots"].values()):
        paths = filter(private, candidates(root, prose))
        found.update(path.name for path in paths)
    return sorted(found)


def candidates(root, prose):
    if ".yml" not in prose and ".yaml" not in prose:
        return
    # Include literal absolute paths with spaces even when the user didn't quote them.
    absolute = ABSOLUTE_YAML.format(root=re.escape(str(root)))
    names = set(re.findall(absolute, prose))
    for quoted, plain in YAML_PATH.findall(prose):
        names.add(quoted or plain)
    for path in project_paths(root, names):
        if root in path.parents and inventory.NAME_PATTERN.fullmatch(path.name):
            yield path


def project_paths(root, names):
    yield from (root / name for name in names)
    basenames = {name for name in names if Path(name).name == name}
    if basenames:
        for relative in project_files.listing(root):
            if Path(relative).name in basenames:
                yield root / relative


def private(path):
    try:
        with inventory_file.opened(path) as stream:
            raw = inventory_file.read_descriptor(stream.fileno())
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    # YAML may encode a literal key with Unicode escapes or a continued quoted scalar.
    if b"\x00" in raw or ESCAPED_KEY.search(raw):
        return True
    return any(field in raw for field in PASSWORD_FIELDS)
