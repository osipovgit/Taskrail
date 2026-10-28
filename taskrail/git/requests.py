"""Intermediate Git contract and immutable output locations."""

import json
from pathlib import Path

from taskrail.core import prompt_texts, schema
from taskrail.git import envelopes

STATUS = "GIT_REQUEST"
STATUS_KEY = "status"
ROOT = "root"
RECENT_ACTIONS = 8


def extract(text):
    """Validate exact request fields; only read operations tolerate surrounding prose."""
    try:
        payload = json.loads(text, object_pairs_hook=schema.unique_fields)
    except ValueError:
        payload = envelopes.read_request(text)
    if not isinstance(payload, dict) or payload.get(STATUS_KEY) != STATUS:
        return None
    schema.require(
        set(payload) == {"schema_version", STATUS_KEY, ROOT, "argv", "reason"},
        "Invalid Git request fields",
    )
    schema.contract_version(payload["schema_version"])
    schema.require(
        isinstance(payload["reason"], str) and bool(payload["reason"].strip()),
        "Git request needs a reason",
    )
    return payload


def output_directory(run):
    """Trusted executor evidence is separate from editable project sources."""
    return run / "00-input" / "git"


def instructions(stage):
    """Git reads for every stage; writes only for the implementer."""
    advertised = [prompt_texts.text("routes.git")]
    if stage == "implementer":
        advertised.append(prompt_texts.text("routes.git.writes"))
    return " ".join(advertised)


def history(run):
    """Reuse completed actions; an interrupted action requires reconciliation."""
    ledger = run / "git-execution.json"
    return json.loads(ledger.read_text()) if ledger.exists() else []


def context(run):
    """Snapshots contain untrusted command output, not instructions."""
    entries = history(run)
    schema.require(
        not any(entry[STATUS_KEY] in {"RUNNING", "UNKNOWN"} for entry in entries),
        prompt_texts.text("git.unknown"),
    )
    if not entries:
        return ""
    recent = list(map(brief, entries[-RECENT_ACTIONS:]))
    index = dict(total_actions=len(entries), recent=recent)
    return prompt_texts.text("git.index") + json.dumps(index)


def brief(entry):
    """Send bounded action identities instead of repeating complete requests and metadata."""
    request = entry["request"]
    return dict(
        id=entry.get("id"),
        operation=request["argv"][0],
        root=request[ROOT],
        status=entry[STATUS_KEY],
        output_file=entry.get("output_file"),
    )


def root_path(payload, roots):
    """Do not grant access to a guessed path or a repository's parent directory."""
    schema.require(isinstance(payload[ROOT], str), "Git root must be text")
    root = Path(payload[ROOT])
    schema.require(
        root in roots.values() and root.resolve() == root,
        "Git root must exactly match a declared root",
    )
    return root
