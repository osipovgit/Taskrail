"""Persist delivered executor output as attributable evidence, not model claims."""

from taskrail.application import evidence, evidence_delivery
from taskrail.core import prompt_texts
from taskrail.core.files import atomic_json
from taskrail.interactions import output_digest, output_preview, read_receipts

INLINE_LIMIT = 24000
# With full text files beside the snapshot, a shorter inline copy saves model context.
INLINE_WITH_FILES = 8000
OUTPUTS = "outputs"


def delivered(folder, path, text, outputs=None):
    """Record exactly the text attached to the next model turn."""
    visible = text[: INLINE_WITH_FILES if outputs else INLINE_LIMIT]
    clipped = len(visible) < len(text)
    line_count = len(visible.splitlines())
    records = [
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
    ]
    text = snapshot_text(path, visible, clipped, outputs)
    evidence_delivery.queue(folder, text, records)
    return text


def snapshot_text(path, visible, clipped, outputs):
    """The bounded snapshot and exact instructions carried by its delivery."""
    notice = "Complete output."
    if clipped:
        notice = "Output clipped; read omitted lines from the full text files: {}".format(
            ", ".join((outputs or {}).values()) or str(path)
        )
    if outputs:
        notice = f"{notice}\n{output_digest.summary(outputs)}"
    return "{}\n{}\n{}".format(prompt_texts.text("output.snapshot", path=path), notice, visible)


def command_snapshot(folder, request, outcome, *, source="local", index=None):
    """Publish a stage-owned receipt with readable sidecars before delivering its text."""
    directory = folder.parent / "00-input" / source
    directory.mkdir(parents=True, exist_ok=True)
    path = next_snapshot(directory, folder.name)
    outputs = output_files(path, outcome)
    entry = dict(request=request, result=outcome)
    if outputs:
        entry[OUTPUTS] = outputs
    atomic_json(path, entry)
    if index and outcome.get("status") == "SUCCEEDED":
        read_receipts.remember(index, path)
    if outputs or path.stat().st_size > INLINE_LIMIT:
        return output_preview.render(path, outcome, outputs)
    return delivered(folder, path, path.read_text(), outputs)


def next_snapshot(directory, stage):
    """A partial sidecar reserves its number even when its JSON receipt could not be published."""
    existing = directory.glob(f"{stage}-*")
    occupied = {path.name.partition(".")[0] for path in existing}
    number = 0
    while f"{stage}-{number}" in occupied:
        number += 1
    return directory / f"{stage}-{number}.json"


def output_files(path, outcome):
    """Long outputs also as plain text beside the snapshot, readable line by line."""
    files = {}
    for name in output_preview.OUTPUT_FIELDS:
        text = outcome.get(name)
        if isinstance(text, str) and len(text) > output_preview.LINE_LIMIT:
            target = path.with_name(f"{path.stem}.{name}.txt")
            output_preview.immutable_text(target, text)
            files[name] = str(target)
    return files
