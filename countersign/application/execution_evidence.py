"""Bind runtime claims to completed, server-recorded local or SSH execution."""

import json

from countersign.interactions import transcripts


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
    return confirmed


def claim_ids(run, claims):
    """The regular quotation validator still verifies every referenced source read."""
    trusted = confirmed_paths(run) | transcripts.confirmed_paths(run)
    return {claim["id"] for claim in claims if claim["path"] in trusted}


def matches(path, entry):
    """Only regular snapshots exactly matching their terminal ticket are trusted."""
    if not path.is_file() or path.is_symlink():
        return False
    snapshot = json.loads(path.read_text())
    if not isinstance(snapshot, list) or not snapshot:
        return False
    return snapshot[-1] == entry
