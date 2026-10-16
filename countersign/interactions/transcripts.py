"""Persist delivered executor output as attributable evidence, not model claims."""

import json
from pathlib import Path

from countersign.application import evidence
from countersign.core.files import atomic_json

INLINE_LIMIT = 24000


def delivered(run, folder, path, text):
    """Record exactly the text attached to the next model turn."""
    visible = text[:INLINE_LIMIT]
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
    notice = (
        "Output clipped; use targeted reads of the snapshot for omitted evidence."
        if clipped
        else "Complete output."
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
    atomic_json(path, entry)
    entries.append(entry)
    atomic_json(ledger, entries)
    return delivered(run, folder, path, path.read_text())


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
    return confirmed
