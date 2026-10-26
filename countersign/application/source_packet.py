"""Bounded current source ranges delivered directly to an independent stage."""

import json
from pathlib import Path

from countersign.application import evidence, source_delivery, source_windows
from countersign.core import protected_paths, schema, source_claims
from countersign.core.files import atomic_json

PACKET_BYTES = source_delivery.PACKET_BYTES
RANGE_LINES = 80


def location(run, stage):
    """Internal handle registry; source text itself travels in the request."""
    return run / f"source-packet-{stage}.json"


def prepare(run, stage, roots, supplied=(), protected=protected_paths.DEFAULT_PATTERNS):
    """Deliver explicit entry points and current reads, never model conclusions."""
    packet = []
    records = list(supplied) + list(reversed(evidence.validation_records(run)))
    for record in records:
        entry = candidate(record, roots, protected)
        if entry is None:
            continue
        source_delivery.append(packet, entry)
    atomic_json(location(run, stage), packet)
    source_delivery.retain(run, location(run, stage), packet)
    return packet


def candidate(record, roots, protected):
    """Return only exact numbered lines within currently declared source roots."""
    path = Path(record["input"]["filePath"])
    inside = any(root in path.parents for root in roots.values())
    permitted = inside and source_windows.permitted(path, protected)
    if not permitted or not evidence.current(record):
        return None
    lines = source_claims.returned_lines(record)
    selected = sorted(lines)[:RANGE_LINES]
    if not selected:
        return None
    return dict(
        path=str(path),
        source_sha256=record["source_sha256"],
        lines={str(number): lines[number] for number in selected},
    )


def resolve(identifier, start, end, context):
    """A handle grants only its delivered range and exact source version."""
    target = location(context["run"], context["stage"])
    indexed = packet_index(target)
    schema.require(identifier in indexed, f"Unknown delivered source handle: {identifier}")
    entry = indexed[identifier]
    current = evidence.fingerprint(Path(entry["path"]))
    schema.require(
        current == entry["source_sha256"], f"Stale source handle: {identifier}; read current source"
    )
    visible = contains(entry["lines"], start, end)
    schema.require(visible, f"Source handle {identifier} does not contain this complete range")
    return entry["path"]


def packet_index(target):
    """Load only server-written stage-local handles."""
    packets = json.loads(target.read_text()) if target.is_file() else []
    return {entry["handle"]: entry for entry in packets}


def contains(lines, start, end):
    """Every requested position must have appeared in the delivered packet."""
    positions = range(start, end + 1)
    return all(str(number) in lines for number in positions)
