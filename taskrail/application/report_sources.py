"""Resolve only a selected executor's actual receipt and the streams it records."""

import json
import re
from pathlib import Path

from taskrail.application import executor_streams
from taskrail.core import prompt_texts, protected_paths, read_hints, schema
from taskrail.core.files import digest, stream_digest
from taskrail.interactions import output_preview

KINDS = frozenset(("local", "git", "checks", "remote"))
STREAM = re.compile(r"(.+)\.(?:\d+-)?(?:stdout|stderr|console|output)\.txt")
OUTPUTS = (*output_preview.OUTPUT_FIELDS, "output")


def executor_path(run, path):
    """Only direct files in the run's four immutable executor directories."""
    return path.parent.parent == run / "00-input" and path.parent.name in KINDS


def selected(run, hints, protected):
    """Group multiple references to one receipt without reparsing large JSON outputs."""
    files = {}
    for hint in hints:
        path = Path(read_hints.split_hint(hint)[0])
        if executor_path(run, path):
            if path not in files:
                files.update(report(path, protected))
        elif run in path.parents:
            schema.require(
                run / "00-input/original" in path.parents,
                prompt_texts.text("validation.split_read_private", path=path),
            )
    return files


def regular(path, protected):
    """A report cannot grant a new read through an alias or a protected name."""
    canonical = path.resolve() == path and path.is_file()
    schema.require(
        canonical and not protected_paths.matches(path, protected), f"Invalid report: {path}"
    )


def report(path, protected):
    """A sidecar only travels if its content matches its producing execution record."""
    regular(path, protected)
    if path.parent.name == "git":
        return {path: stream_digest(path)}
    match = STREAM.fullmatch(path.name)
    receipt = path.with_name(f"{match[1]}.json") if match else path
    regular(receipt, protected)
    schema.require(receipt.suffix == ".json", f"Expected an executor receipt: {receipt}")
    encoded = receipt.read_bytes()
    try:
        files = _streams(receipt, json.loads(encoded), protected)
    except (TypeError, LookupError, AttributeError) as error:
        raise ValueError(f"Invalid executor receipt: {receipt}") from error
    files[receipt] = digest(encoded)
    schema.require(path in files, f"Stream not recorded by its executor: {path}")
    return files


def _streams(receipt, entry, protected):
    hashes = recorded_hashes(receipt.parent.name, entry)
    files = {}
    for name, expected in hashes.items():
        path = receipt.with_suffix(f".{name}.txt")
        regular(path, protected)
        schema.require(stream_digest(path) == expected, f"Recorded executor output changed: {path}")
        files[path] = expected
    return files


def recorded_hashes(kind, entry):
    """Derive locations from executor-owned stream names, never a path inside output."""
    if kind == "checks":
        streams = entry["execution"]["artifacts"]
        return {name: streams[name]["sha256"] for name in OUTPUTS if name in streams}
    if kind == "remote" and "results" in entry:
        streams = output_preview.ticket_streams(entry)
        return {name: digest(text.encode()) for name, text in streams.items()}
    schema.require(isinstance(entry["result"], dict), "Invalid command report")
    streams = executor_streams.streams(entry)
    selected = entry.get("outputs", {}).keys() & OUTPUTS
    return {name: digest(streams[name].encode()) for name in selected}
