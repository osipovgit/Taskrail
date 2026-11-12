"""Display root references as absolute paths while retaining internal scope keys."""

import re
from pathlib import Path

from taskrail.core.plan_keys import RUN_COMMAND
from taskrail.core.schema import require


def tool_paths(payload, roots):
    """Render source references as absolute paths, without replacing inside absolute paths."""
    if isinstance(payload, dict):
        return {key: tool_paths(element, roots) for key, element in payload.items()}
    if isinstance(payload, list):
        return [tool_paths(element, roots) for element in payload]
    if isinstance(payload, str) and not payload.lower().startswith(RUN_COMMAND):
        for alias, root in roots.items():
            payload = re.sub(
                rf"(?<![\w/.-]){re.escape(alias)}/",
                f"{root!s}/".replace("\\", r"\\"),
                payload,
            )
    return payload


def readable_source(name, roots):
    """Resolve a source read without granting the stronger edit authorization."""

    require(isinstance(name, str), "Read path must be text")
    alias, separator, relative = name.partition("/")
    require(bool(separator) and alias in roots, "Unknown source root")
    path = roots[alias] / relative
    require(path.resolve() == path, "Noncanonical source read")
    require(roots[alias] in path.parents and path.is_file(), "Source file outside root or absent")
    return path


def absolute(name, roots):
    """An absolute path, `alias/relative`, or a path relative to the only root."""
    path = Path(name)
    if path.is_absolute():
        return path
    alias, _, relative = name.partition("/")
    if alias in roots and relative:
        return Path(roots[alias]) / relative
    if len(roots) == 1:
        return Path(next(iter(roots.values()))) / name
    return path
