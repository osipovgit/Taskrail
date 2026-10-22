"""Bind runtime claims to completed, server-recorded local or SSH execution."""

import json
from pathlib import Path

from countersign.application import check_results
from countersign.interactions import output_preview, transcripts


def confirmed_paths(run):
    """Snapshots must match their ledger entry, not just contain plausible output."""
    ledger = run / "execution.json"
    if not ledger.is_file():
        return set()
    confirmed = set()
    for entry in json.loads(ledger.read_text()):
        if entry.get("status") != "SUCCEEDED":
            continue
        path = run / "00-input" / "ssh" / "{}.json".format(entry["id"])
        if matches(path, entry):
            confirmed.add(str(path))
            confirmed.update(confirmed_outputs(path, entry))
    return confirmed


def confirmed_outputs(path, entry):
    """Plain-text copies count only while they match this successful ticket."""
    streams = output_preview.ticket_streams(entry)
    return {
        target
        for name, target in output_preview.ticket_outputs(path, entry).items()
        if transcripts.unchanged(Path(target), streams[name])
    }


def claim_ids(run, claims):
    """Only current, criterion-bound checks can substantiate runtime acceptance."""
    trusted = check_results.trusted(run)
    bound = {}
    for claim in claims:
        recorded = trusted.get(claim["path"])
        if recorded:
            bound[claim["id"]] = recorded
    return bound


def matches(path, entry):
    """Only regular snapshots exactly matching their terminal ticket are trusted."""
    if not path.is_file() or path.is_symlink():
        return False
    snapshot = json.loads(path.read_text())
    if not isinstance(snapshot, list) or not snapshot:
        return False
    return snapshot[-1] == entry
