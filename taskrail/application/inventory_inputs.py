"""Remember operator-named project paths before agents can propose executable inventories."""

import re
from pathlib import Path

from taskrail.application import project_files

KEY = "inventory_inputs"
WORDS = re.compile(r"[`\"']([^`\"'\n]+)[`\"']|([^\s`\"'<>|]+)")


def capture(config):
    if KEY in config:
        return
    inputs = set()
    fields = config.get("task_spec", {}).get("fields", [])
    if not config.get("phase"):
        roots = {original for _, original in checkouts(config)}
        for root in roots:
            inputs.update(mentioned(root, fields))
    config[KEY] = sorted(map(str, inputs))


def mentioned(root, fields):
    for field in fields:
        for quoted, plain in WORDS.findall(field["text"]):
            name = quoted or plain.rstrip(".,:;!?)]}")
            path = root / name
            if root in path.parents and candidate(path):
                yield path


def candidate(path):
    try:
        return (path.is_file() or path.is_dir()) and path.resolve() == path
    except (OSError, RuntimeError, ValueError):
        return False


def original_root(record, root):
    return Path(record.get("original_source", record.get("source", root)))


def checkouts(config):
    for alias, root in config["roots"].items():
        record = config.get("worktrees", {}).get(alias, {})
        original = original_root(record, root)
        for checkout in (Path(root), Path(record.get("source", root)), original):
            yield checkout, original


def files(root, inputs):
    for path in inputs:
        if root not in path.parents:
            continue
        relative = path.relative_to(root)
        if path.is_dir():
            yield from (relative / name for name in project_files.listing(path))
        else:
            yield relative


def locations(copies, inputs):
    for root in copies:
        for source in inputs:
            if root in source.parents:
                yield root, source
