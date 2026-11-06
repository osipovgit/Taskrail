"""Map planning targets from authenticated source checkouts to effective worktrees.

Only future targets and read hints are translated. Observations, evidence claims,
user text and executor requests always keep their actual paths.
"""

from functools import partial
from pathlib import Path

from taskrail.application import worktree_default
from taskrail.core import prompt_texts


def mappings(config):
    """Only recorded worktrees that exactly match the effective roots supply aliases."""
    found = []
    for alias, entry in config.get("worktrees", {}).items():
        target = Path(entry["worktree"])
        if target != config["roots"].get(alias):
            continue
        found.extend(
            (origin, target) for origin in worktree_default.origins(entry) if origin != target
        )
    return sorted(found, key=source_depth, reverse=True)


def source_depth(pair):
    """More specific source repositories take precedence over their parent checkout."""
    return len(pair[0].parts)


def resolve(name, mapping):
    """Translate a canonical exact source path; never guess another run or sibling root."""
    path = Path(name)
    if not path.is_absolute() or path.resolve() != path:
        return path
    if any(target in path.parents for _, target in mapping):
        return path
    for origin, target in mapping:
        if origin in path.parents:
            return target / path.relative_to(origin)
    return path


def plan_targets(payload, config):
    """The approved plan stores effective targets; cited evidence is never relabelled."""
    mapping = mappings(config)
    if not mapping:
        return
    convert = partial(resolve, mapping=mapping)
    read = partial(read_hint, mapping=mapping)
    for step in payload["steps"]:
        step["files"] = [str(convert(name)) for name in step["files"]]
        step["read"] = list(map(read, step.get("read", [])))
    payload["proposed_change_files"] = [
        str(convert(name)) for name in payload["proposed_change_files"]
    ]


def read_hint(hint, mapping):
    """The parser already resolved and validated this path:range, including quoted spaces."""
    name, lines = hint.rsplit(":", 1)
    return f"{resolve(name, mapping)}:{lines}"


def instructions(config):
    """Every stage sees where source paths in unchanged user text belong for this run."""
    mapping = mappings(config)
    if not mapping:
        return ""
    return prompt_texts.text("paths.worktrees")


def public_mapping(config):
    """Paths are request data; keep the execution instruction independent of path lengths."""
    return {str(origin): str(target) for origin, target in mappings(config)}
