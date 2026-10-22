"""Read bounded, explicit source entry points without asking a model to fetch them."""

import re
from pathlib import Path

from countersign.application import evidence, project_files
from countersign.core.paths import tool_paths

REFERENCE = re.compile(r"(.+?)(?::([1-9]\d*)(?:-([1-9]\d*))?)?")
WINDOW_LINES = 40
WINDOW_LIMIT = 40


def requests(config, plan):
    """Prefer approved citation windows, then exact entry points and changed paths."""
    chosen = plan or {}
    cited = [
        "{path}:{line_start}-{line_end}".format(**claim) for claim in chosen.get("evidence", [])
    ]
    explicit = entry_points(config.get("task_spec", {}))
    return (cited + explicit + chosen.get("proposed_change_files", []))[:WINDOW_LIMIT]


def entry_points(spec):
    """Each entry point line must be an exact source reference, not arbitrary prose."""
    fields = spec.get("fields", [])
    entries = [field["text"] for field in fields if field["name"] == "entry_points"]
    lines = [line.strip() for text in entries for line in text.splitlines()]
    return [line.removeprefix("- ").strip("`") for line in lines]


def observations(config, plan):
    """Ignore ambiguous or unavailable hints; normal model reads remain available."""
    records = [
        observe(reference, config["roots"]) for reference in dict.fromkeys(requests(config, plan))
    ]
    return [record for record in records if record is not None]


def observe(reference, roots):
    """Resolve one optional bounded line range within declared roots."""
    match = REFERENCE.fullmatch(tool_paths(reference, roots))
    if match is None:
        return None
    start = int(match[2] or 1)
    maximum = start + WINDOW_LINES - 1
    last = min(int(match[3] or maximum), maximum)
    return read_window(source_path(match[1], roots), start, last)


def source_path(name, roots):
    """Explicit canonical paths cannot escape roots, traverse symlinks or name secrets."""
    path = Path(name)
    if not path.is_absolute() and len(roots) == 1:
        path = next(iter(roots.values())) / path
    inside = any(root in path.parents for root in roots.values())
    if inside and permitted(path):
        return path
    return None


def permitted(path):
    """Only canonical, non-protected source paths can enter a packet."""
    canonical = path.resolve() == path and ".git" not in path.parts
    return canonical and not project_files.protected(str(path))


def read_window(path, start, end):
    """A current exact text window; large, binary and invalid UTF-8 files stay unread."""
    if path is None or not path.is_file():
        return None
    if path.stat().st_size > project_files.MAX_BYTES:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if "\x00" in text or end < start:
        return None
    selected = enumerate(text.splitlines()[start - 1 : end], start)
    output = "\n".join(f"{number}: {line}" for number, line in selected)
    return dict(
        tool="source_packet",
        input=dict(filePath=str(path), offset=start),
        output=output,
        source_sha256=evidence.fingerprint(path),
    )
