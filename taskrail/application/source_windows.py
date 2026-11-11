"""Read bounded, explicit source entry points without asking a model to fetch them."""

from itertools import islice
from pathlib import Path

from taskrail.application import project_files
from taskrail.core import protected_paths, read_hints
from taskrail.core.files import bounded_bytes, digest
from taskrail.core.paths import tool_paths

WINDOW_LINES = 40
WINDOW_LIMIT = 40


def requests(config, plan, extra=()):
    """Prefer approved citation windows, then exact entry points and changed paths."""
    chosen = plan or {}
    cited = [
        "{path}:{line_start}-{line_end}".format(**claim) for claim in chosen.get("evidence", [])
    ]
    for step in chosen.get("steps", []):
        cited.extend(step.get("read", []))
    cited.extend(entry_points(config.get("task_spec", {})))
    cited.extend(chosen.get("proposed_change_files", []))
    eligible = read_hints.scoped(dict.fromkeys(cited), config["roots"], extra)
    return islice(eligible, WINDOW_LIMIT)


def entry_points(spec):
    """Each entry point line must be an exact source reference, not arbitrary prose."""
    fields = spec.get("fields", [])
    entries = [field["text"] for field in fields if field["name"] == "entry_points"]
    lines = [line.strip() for text in entries for line in text.splitlines()]
    return [line.removeprefix("- ").strip("`") for line in lines]


def observations(config, plan):
    """Ignore ambiguous or unavailable hints; normal model reads remain available."""
    scope = (config["roots"], protected_paths.patterns(config))
    records = [observe(reference, *scope) for reference in requests(config, plan)]
    return [record for record in records if record is not None]


def observe(reference, roots, protected):
    """Resolve one optional bounded line range within declared roots."""
    match = read_hints.REFERENCE.fullmatch(tool_paths(reference, roots))
    if match is None:
        return None
    start = int(match[2] or 1)
    maximum = start + WINDOW_LINES - 1
    last = min(int(match[3] or maximum), maximum)
    return read_window(source_path(match[1], roots, protected), start, last)


def source_path(name, roots, protected=protected_paths.DEFAULT_PATTERNS):
    """Explicit canonical paths cannot escape roots, traverse symlinks or name secrets."""
    path = Path(name)
    if not path.is_absolute() and len(roots) == 1:
        path = next(iter(roots.values())) / path
    inside = any(root in path.parents for root in roots.values())
    if inside and permitted(path, protected):
        return path
    return None


def permitted(path, protected=protected_paths.DEFAULT_PATTERNS):
    """Only canonical, non-protected source paths can enter a packet."""
    canonical = path.resolve() == path and ".git" not in path.parts
    return canonical and not protected_paths.matches(path, protected)


def read_window(path, start, end):
    """A current exact text window; large, binary and invalid UTF-8 files stay unread."""
    raw = bounded_bytes(path, project_files.MAX_BYTES)
    if raw is None or b"\x00" in raw or end < start:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return None
    selected = enumerate(text.splitlines()[start - 1 : end], start)
    return dict(
        tool="source_packet",
        input=dict(filePath=str(path), offset=start),
        output="\n".join(f"{number}: {line}" for number, line in selected),
        source_sha256=digest(raw),
    )
