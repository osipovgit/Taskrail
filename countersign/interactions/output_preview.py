"""Bounded executor summaries and immutable, line-readable remote outputs."""

from pathlib import Path

from countersign.interactions import output_digest

LINE_LIMIT = 2000
OUTPUT_FIELDS = ("stdout", "stderr", "console")
PREVIEW_CHARS = 500
RESULT_FIELDS = ("status", "target", "exit_code", "detail", "reason")
DIGEST_STREAMS = 8
PREVIEW_LIMIT = 24000


def render(path, outcome, outputs):
    """Status and independent stream previews; the full snapshot remains readable evidence."""
    fields = [f"{name}: {outcome[name]}" for name in RESULT_FIELDS if name in outcome]
    streams = [
        f"{name}: {excerpt(outcome[name])}"
        for name in (*OUTPUT_FIELDS, "output")
        if isinstance(outcome.get(name), str) and outcome[name]
    ]
    digest = dict(list(outputs.items())[:DIGEST_STREAMS])
    digest = output_digest.summary(digest)
    references = "Full output files: {}".format(excerpt(", ".join(outputs.values())))
    return "\n".join(
        [
            *map(excerpt, fields),
            f"Executor evidence snapshot: {path}. Read exact lines before citing it.",
            *streams,
            excerpt(digest),
            references if outputs else "",
        ]
    )


def excerpt(text):
    """A bounded head and tail retain short errors beside long progress streams."""
    if len(text) <= PREVIEW_CHARS * 2:
        return text
    head, tail = text[:PREVIEW_CHARS], text[-PREVIEW_CHARS:]
    return f"{head}\n[... omitted; read the saved output ...]\n{tail}"


def ticket_streams(entry):
    """Named streams of one remote ticket, without earlier tickets' outputs."""
    streams = {}
    for number, outcome in enumerate(entry.get("results", []), 1):
        for name in (*OUTPUT_FIELDS, "output"):
            text = outcome.get(name)
            if isinstance(text, str) and len(text) > LINE_LIMIT:
                streams[f"{number}-{name}"] = text
    return streams


def ticket_outputs(path, entry):
    """Deterministic plain-text paths for long remote output streams."""
    pattern = str(path.with_suffix(".{0}.txt"))
    return {name: pattern.format(name) for name in ticket_streams(entry)}


def immutable_text(path, text):
    """Create a snapshot once; a changed existing snapshot is an integrity failure."""
    if path.is_symlink():
        raise ValueError(f"Executor evidence snapshot changed: {path}")
    if path.exists():
        if path.read_bytes().decode("utf-8") != text:
            raise ValueError(f"Executor evidence snapshot changed: {path}")
        return
    path.write_text(text, encoding="utf-8")


def ticket_preview(path, pending):
    """Only the latest ticket's bounded outcomes enter the next model turn."""
    outputs = ticket_outputs(path, pending)
    shown = (pending.get("id"), pending.get("status"), path)
    previews = ["Ticket {}: {}; evidence: {}".format(*shown)]
    for outcome in pending.get("results", []):
        shown = (outcome.get("target", "Jenkins"), outcome.get("status", "recorded"))
        previews.append("Target {}: {}".format(*shown))
    previews.append(render(path, pending, outputs))
    for outcome in pending.get("results", []):
        shown = render(path, outcome, {})
        previews.append(excerpt(shown))
    shown = "\n".join(previews)
    if len(shown) > PREVIEW_LIMIT:
        clipped = shown[:PREVIEW_LIMIT]
        return f"{clipped}\n[Preview clipped; read the ticket snapshot.]"
    return shown


def save_ticket_outputs(destination, pending):
    """Write each remote stream once beside the stable ticket snapshot."""
    streams = ticket_streams(pending)
    for name, target in ticket_outputs(destination, pending).items():
        immutable_text(Path(target), streams[name])
