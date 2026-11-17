"""Remember operator-named project paths before agents can propose executable inventories."""

import re
from pathlib import Path

from taskrail.application import project_files

KEY = "inventory_inputs"
WORDS = re.compile(r"[`\"']([^`\"'\n]+)[`\"']|([^\s`\"'<>|]+)")


def capture(config, inherited=()):
    """Only the sealed parent and this turn's operator fields can name trusted sources."""
    if KEY in config:
        return
    inputs = set(inherited)
    fields = config.get("task_spec", {}).get("fields", [])
    if not config.get("phase"):
        roots = {original for _, original in checkouts(config)}
        for root in roots:
            inputs.update(map(str, mentioned(root, fields)))
    config[KEY] = sorted(inputs)


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


def files(root, relative_sources):
    for relative in relative_sources:
        path = root / relative
        if path.is_dir() and candidate(path):
            yield from (relative / name for name in project_files.listing(path))
        else:
            yield relative
