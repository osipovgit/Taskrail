"""Immutable check evidence bound to exact criteria, requests and reviewed source."""

import json
from pathlib import Path

from taskrail.application import check_artifacts, source_ignores
from taskrail.application.git_state import git_metadata
from taskrail.core.files import atomic_json, digest
from taskrail.executor import protocol

LEDGER = "check-results.json"
IDENTITY_LENGTH = 20


def source_identity(roots):
    """A check applies only while both its source and repository identity match."""
    payload = dict(source=source_ignores.current(roots), git=git_metadata(roots))
    return digest(json.dumps(payload, sort_keys=True).encode())


def record(run, spec, request, outcome, context):
    """Publish evidence after the request and its source boundary have been verified."""
    entries = read(run)
    result_id = result_name(spec, len(entries), request)
    path = run / "00-input/checks" / f"{result_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(
        schema_version=1,
        id=result_id,
        check_id=spec["id"],
        criteria=spec["criteria"],
        request_sha256=protocol.fingerprint(request),
        source_snapshot=context["source_snapshot"],
        assessment=context["assessment"],
        execution=check_artifacts.stored_output(path, outcome),
        path=str(path),
    )
    atomic_json(path, entry)
    entries.append(entry)
    atomic_json(run / LEDGER, entries)
    return entry


def result_name(spec, sequence, request):
    """A short, stable ID for the nth result of one check request."""
    identity = dict(check=spec["id"], sequence=sequence, request=request)
    digest = protocol.fingerprint(identity)[:IDENTITY_LENGTH]
    return f"check-{digest}"


def read(run):
    """Read only the current run's server-owned check ledger."""
    path = run / LEDGER
    return json.loads(path.read_text()) if path.is_file() else []


def trusted(run):
    """Forged snapshots, stale source and unknown results never substantiate acceptance."""
    entries = {entry["check_id"]: entry for entry in read(run)}
    if not entries:
        return {}
    current = source_identity(stored_roots(run))
    return {entry["path"]: entry for entry in entries.values() if valid(entry, current)}


def stored_roots(run):
    """Source roots are read from the run's server-owned index."""
    state = json.loads((run / "run.json").read_text())
    return {name: Path(location) for name, location in state["roots"].items()}


def valid(entry, current):
    """The serialized evidence must still equal its durable completion record."""
    path = Path(entry["path"])
    if path.is_symlink() or not path.is_file() or entry["source_snapshot"] != current:
        return False
    if entry["assessment"]["status"] not in {"passed", "failed"}:
        return False
    matches = json.loads(path.read_text()) == entry
    return matches and check_artifacts.valid(entry["execution"])
