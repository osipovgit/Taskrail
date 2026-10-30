"""Give the session the exact current lines a rejected citation names.

A citation fails when no read of the run returned its lines in full. Asking the model
to read again often fails the same way (a truncated or skipped window), and a failed
stage starts a new session that must rebuild its context. When the lines are permitted
and still current, the correction carries their text and records it as an observation,
so the same session only checks its claim against them.
"""

from pathlib import Path

from taskrail.application import evidence, evidence_delivery, source_windows
from taskrail.core import prompt_texts, protected_paths, source_lines

DELIVERED_LINES = 60
DELIVERED_BYTES = 4000


def deliver(error, context):
    """Prepare bounded correction text; it is not evidence until a turn receives it."""
    path = Path(error.path)
    if not deliverable(path, error, context):
        return None
    lines = numbered(error.missing, sorted(error.missing))
    text = prompt_texts.text("citation.delivered", label=error.label, lines=lines)
    records = [
        observation(context["run"], path, error, window)
        for window in source_lines.windows(error.missing)
    ]
    evidence_delivery.queue(context["folder"], text, records)
    return text


def numbered(missing, numbers):
    """Lines in the numbered read format."""
    return "\n".join(f"{number}: {missing[number]}" for number in numbers)


def deliverable(path, error, context):
    """A bounded, current, permitted window inside the declared roots."""
    if not permitted(path, context) or not bounded(error.missing):
        return False
    return evidence.fingerprint(path) == error.source_sha256


def permitted(path, context):
    """Inside a declared root and not a protected path."""
    roots = [Path(root) for root in context["roots"].values()]
    protected = protected_paths.patterns(context.get("check_config") or {})
    inside = any(root in path.parents for root in roots)
    return inside and source_windows.permitted(path, protected)


def bounded(missing):
    """Few and short enough lines; larger gaps keep the read windows and source views."""
    size = sum(len(line.encode()) for line in missing.values())
    return 0 < len(missing) <= DELIVERED_LINES and size <= DELIVERED_BYTES


def observation(run, path, error, window):
    """The delivered lines of one window, like a model read of exactly them."""
    start, end = window
    lines = range(start, end + 1)
    output = numbered(error.missing, lines)
    return dict(
        tool="citation_delivery",
        input=dict(filePath=str(path), offset=start, limit=len(lines)),
        output=output,
        source_sha256=error.source_sha256,
        source_event=str(run / evidence.OBSERVATIONS),
        event_line=start,
        call_id=f"citation-{start}-{end}",
        original_chars=len(output),
        saved_chars=len(output),
        output_clipped=False,
        upstream_truncated=False,
    )
