"""Find exact existing text streams when a snapshot's JSON string is too long to read."""

import json

from taskrail.core import prompt_texts
from taskrail.interactions import output_preview

MAX_BYTES = 8 * 1024 * 1024


def guidance(run, path):
    """Pointers are not observations: the receiving session must read their lines."""
    permitted = path.parent in {run / "00-input/local", run / "00-input/remote"}
    if not permitted or path.suffix != ".json" or path.resolve() != path:
        return None
    try:
        return describe(path)
    except (OSError, ValueError, RecursionError):
        return None


def describe(path):
    """Bound parsing and accept only sidecars matching their exact snapshot value."""
    if path.stat().st_size > MAX_BYTES:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = []
    for name, text in streams(payload).items():
        reference = verified(path, name, text)
        if reference:
            files.append(reference)
    return prompt_texts.text("citation.executor_streams", files="\n".join(files)) if files else None


def streams(payload):
    """Only the current local result or single immutable remote ticket contributes."""
    if not isinstance(payload, dict):
        return {}
    outcomes = payload.get("results")
    if isinstance(outcomes, list):
        valid = all(isinstance(outcome, dict) for outcome in outcomes)
        return output_preview.ticket_streams(payload) if valid else {}
    outcome = payload.get("result")
    if not isinstance(outcome, dict):
        return {}
    return {
        name: text
        for name, text in outcome.items()
        if name in output_preview.OUTPUT_FIELDS and isinstance(text, str)
    }


def verified(snapshot, name, text):
    """Never follow a sidecar symlink or trust a path supplied by command output."""
    path = snapshot.with_suffix(f".{name}.txt")
    if not readable(path):
        return None
    if path.read_bytes().decode("utf-8") != text:
        return None
    return f"{path}:1-{len(text.splitlines())}"


def readable(path):
    """A bounded real file at its canonical location."""
    if path.resolve() != path or not path.is_file():
        return False
    return path.stat().st_size <= MAX_BYTES
