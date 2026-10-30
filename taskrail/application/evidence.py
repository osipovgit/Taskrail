"""Carry attributed source reads across attempts, invalidating changed content."""

import hashlib
import json
from pathlib import Path

from taskrail.application.recovery import complete_evidence
from taskrail.core.files import atomic_json

OMITTED = "omitted"
RECORDS = "records"
OBSERVATIONS = "observations.json"
MAX_RECORDS = 60
MAX_CHARACTERS = 240000


def fingerprint(path):
    """Hash bytes only for an existing regular source file."""
    if path.is_file() and not path.is_symlink():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def load_index(run, filename="evidence.json"):
    """Load reusable observations; missing indexes are valid for older runs."""
    index = run / filename
    if index.is_file():
        return json.loads(index.read_text())
    return {"source": str(index), RECORDS: [], OMITTED: 0}


def current(record):
    """Discard observations whose source bytes no longer match their version."""
    return fingerprint(Path(record["input"]["filePath"])) == record["source_sha256"]


def observed_reads(batch, events):
    """Attach source identities to successful reads, retaining truncation flags."""
    for record in batch[RECORDS]:
        if record["tool"] == "read":
            source_hash = fingerprint(Path(record["input"]["filePath"]))
            if source_hash:
                record.update(source_sha256=source_hash, source_event=str(events))
                yield record


def refresh(run, events, roots):
    """Keep validation observations complete and bound only model recovery context."""
    index = load_index(run, OBSERVATIONS)
    batch = complete_evidence(events, roots)
    records = [record for record in index[RECORDS] if current(record)]
    records.extend(observed_reads(batch, events))
    unique = {
        (
            json.dumps(record["input"], sort_keys=True),
            record["source_sha256"],
            record["tool"],
            hashlib.sha256(record["output"].encode()).digest(),
            record.get("output_clipped", False),
            record.get("audience"),
            record.get("session_id"),
            record.get("source_event"),
        ): record
        for record in records
    }
    index[RECORDS] = list(unique.values())
    atomic_json(run / OBSERVATIONS, index)
    retained = bounded(list(unique.values()))
    index[OMITTED] += batch[OMITTED]
    index.update(
        source=str(run / "evidence.json"),
        records=retained,
        omitted=index[OMITTED] + len(unique) - len(retained),
    )
    atomic_json(run / "evidence.json", index)
    return index


def validation_records(run):
    """Reusable discovery records; these alone do not prove delivery to a new session."""
    return load_index(run, OBSERVATIONS)[RECORDS]


def bounded(records):
    """Prefer recent ranges while enforcing a bounded recovery payload."""
    retained = []
    remaining = MAX_CHARACTERS
    for record in reversed(records):
        if len(retained) >= MAX_RECORDS:
            break
        if len(record["output"]) > remaining:
            continue
        remaining -= len(record["output"])
        retained.append(record)
    return list(reversed(retained))
