"""Display root references as absolute paths while retaining internal scope keys."""

import re

from countersign.core.schema import require


def tool_paths(payload, roots):
    """Render source references as absolute paths, without replacing inside absolute paths."""
    if isinstance(payload, dict):
        return {key: tool_paths(element, roots) for key, element in payload.items()}
    if isinstance(payload, list):
        return [tool_paths(element, roots) for element in payload]
    if isinstance(payload, str):
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
