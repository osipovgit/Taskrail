"""Persist delivered executor output as attributable evidence, not model claims."""

import json
from pathlib import Path

from countersign.application import evidence
from countersign.core.files import atomic_json

INLINE_LIMIT = 24000
# With full text files beside the snapshot, a shorter inline copy saves model context.
INLINE_WITH_FILES = 8000
# The JSON snapshot keeps each output on one line; file readers cut lines this long.
LINE_LIMIT = 2000
OUTPUT_FIELDS = ("stdout", "stderr", "console")


def delivered(run, folder, path, text, outputs=None):
    """Record exactly the text attached to the next model turn."""
    visible = text[: INLINE_WITH_FILES if outputs else INLINE_LIMIT]
    clipped = len(visible) < len(text)
    line_count = len(visible.splitlines())
    index = evidence.load_index(run, evidence.OBSERVATIONS)
    index["records"].append(
        dict(
            tool="executor",
            input=dict(filePath=str(path), offset=1, limit=line_count),
            output=visible,
            source_sha256=evidence.fingerprint(path),
            source_event=str(folder / "events.jsonl"),
            event_line=len((folder / "events.jsonl").read_text().splitlines()),
            output_clipped=clipped,
            upstream_truncated=False,
        )
    )
    atomic_json(run / evidence.OBSERVATIONS, index)
    notice = "Complete output."
    if clipped:
        notice = "Output clipped; read omitted lines from the full text files: {0}".format(
            ", ".join((outputs or {}).values()) or str(path)
        )
    return f"Evidence snapshot (cite this path, never tool-result.md): {path}\n{notice}\n{visible}"


def local_snapshot(run, folder, request, outcome):
    """The ledger binds a result to its exact request and immutable snapshot."""
    ledger = run / "local-execution.json"
    entries = json.loads(ledger.read_text()) if ledger.exists() else []
    count = len(entries)
    path = run / "00-input/local" / f"{folder.name}-{count}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(request=request, result=outcome, path=str(path))
    entry["outputs"] = output_files(path, outcome)
    atomic_json(path, entry)
    entries.append(entry)
    atomic_json(ledger, entries)
    return delivered(run, folder, path, path.read_text(), entry["outputs"])


def output_files(path, outcome):
    """Long outputs also as plain text beside the snapshot, readable line by line."""
    files = {}
    for name in OUTPUT_FIELDS:
        text = outcome.get(name)
        if isinstance(text, str) and len(text) > LINE_LIMIT:
            target = path.with_name(f"{path.stem}.{name}.txt")
            target.write_text(text, encoding="utf-8")
            files[name] = str(target)
    return files


def confirmed_paths(run):
    """Only matching successful local results can substantiate runtime claims."""
    ledger = run / "local-execution.json"
    entries = json.loads(ledger.read_text()) if ledger.exists() else []
    confirmed = set()
    for entry in entries:
        path = Path(entry["path"])
        if entry["result"].get("status") == "SUCCEEDED" and evidence.fingerprint(path):
            if json.loads(path.read_text()) == entry:
                confirmed.add(str(path))
                confirmed.update(matching_outputs(entry))
    return confirmed


def matching_outputs(entry):
    """Text copies whose content still equals the recorded output."""
    recorded = entry["result"]
    outputs = entry.get("outputs", {}).items()
    return {target for name, target in outputs if unchanged(target, recorded[name])}


def unchanged(target, text):
    """A regular file that still holds exactly the recorded text."""
    path = Path(target)
    return evidence.fingerprint(path) is not None and path.read_text() == text
