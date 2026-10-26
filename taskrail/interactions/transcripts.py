"""Persist delivered executor output as attributable evidence, not model claims."""

import json

from taskrail.application import evidence
from taskrail.core.files import atomic_json
from taskrail.interactions import output_digest, output_preview

INLINE_LIMIT = 24000
# With full text files beside the snapshot, a shorter inline copy saves model context.
INLINE_WITH_FILES = 8000
# The JSON snapshot keeps each output on one line; file readers cut lines this long.
LINE_LIMIT = 2000
OUTPUT_FIELDS = ("stdout", "stderr", "console")
OUTPUTS = "outputs"


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
        notice = "Output clipped; read omitted lines from the full text files: {}".format(
            ", ".join((outputs or {}).values()) or str(path)
        )
    if outputs:
        notice = f"{notice}\n{output_digest.summary(outputs)}"
    return f"Evidence snapshot (cite this path, never tool-result.md): {path}\n{notice}\n{visible}"


def local_snapshot(run, folder, request, outcome):
    """The ledger binds a result to its exact request and immutable snapshot."""
    ledger = run / "local-execution.json"
    entries = json.loads(ledger.read_text()) if ledger.exists() else []
    count = len(entries)
    path = run / "00-input/local" / f"{folder.name}-{count}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(request=request, result=outcome, path=str(path))
    entry[OUTPUTS] = output_files(path, outcome)
    atomic_json(path, entry)
    entries.append(entry)
    atomic_json(ledger, entries)
    if entry[OUTPUTS] or path.stat().st_size > INLINE_LIMIT:
        return output_preview.render(path, outcome, entry[OUTPUTS])
    return delivered(run, folder, path, path.read_text(), entry[OUTPUTS])


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
