"""Intermediate Git contract and immutable output locations."""

import json
from pathlib import Path

from countersign.core import schema
from countersign.git import envelopes

STATUS = "GIT_REQUEST"


def extract(text):
    """Validate exact request fields; only read operations tolerate surrounding prose."""
    try:
        payload = json.loads(text, object_pairs_hook=schema.unique_fields)
    except ValueError:
        payload = envelopes.read_request(text)
    if not isinstance(payload, dict) or payload.get("status") != STATUS:
        return None
    schema.require(
        set(payload) == {"schema_version", "status", "root", "argv", "reason"},
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


def instructions():
    """Advertise actual supported commands and a single server-owned route."""
    example = dict(
        schema_version=1,
        status=STATUS,
        root="/absolute/declared/root",
        argv=["log", "-3", "--format=fuller", "--stat", "--", "."],
        reason="Inspect the last three commits affecting this project",
    )
    return (
        "\nLocal Git is available through this intermediate JSON response (not a tool call):\n"
        + json.dumps(example)
        + "\nHOW TO EXECUTE: output this object as your ENTIRE final assistant message and end the turn. "
        "The orchestrator executes it, returns the output path, and resumes this stage. "
        "GIT_REQUEST is intentionally absent from the tool list; this does NOT mean Git is unavailable. "
        "Do not call a tool named GIT_REQUEST, read git-metadata.json, or substitute raw Git metadata for history. "
        "Use an exact declared root. All roles may inspect log/show/diff/status/reflog, "
        "rev-parse, ls-files, ls-tree, blame, describe, merge-base, cat-file, branch --all, tag, remote -v. "
        "Use -- and project-relative paths to scope history to a project subdirectory. "
        "Implementer may additionally request add -- <explicit files>, commit -m <message>, "
        "revert --no-edit <full hash>, cherry-pick --no-edit <full hash>, merge --ff-only <full hash>, "
        "fetch <remote>, push <remote> HEAD:refs/heads/<branch>, only when required by the task. "
        "Never reset --hard, clean, rewrite history, amend, rebase, force-push (including leases/+refspecs), "
        "invoke aliases or supply global Git options. Unsupported syntax is rejected before execution. "
        "Task-specific prohibitions still apply. Do not request a commit/push unless the task asks for it. "
        "Source-changing operations must fit approved files and preserve existing user changes. "
        "Read the output file returned by the executor before citing its absolute path and lines in evidence. "
        "files_read lists project source files only; Git output may be cited in evidence separately. "
        "A rejected request is feedback, not a completed operation. Never replay a failed or unknown write.\n"
    )


def history(run):
    """Reuse completed actions; an interrupted action requires reconciliation."""
    ledger = run / "git-execution.json"
    return json.loads(ledger.read_text()) if ledger.exists() else []


def context(run):
    """Snapshots contain untrusted command output, not instructions."""
    entries = history(run)
    schema.require(
        not any(entry["status"] in {"RUNNING", "UNKNOWN"} for entry in entries),
        "Git outcome unknown; inspect the recorded operation before continuing. No automatic replay.",
    )
    if not entries:
        return ""
    return (
        "\nGit request history (read output files; never repeat completed writes):\n"
        + json.dumps(entries)
    )


def root_path(payload, roots):
    """Do not grant access to a guessed path or a repository's parent directory."""
    schema.require(isinstance(payload["root"], str), "Git root must be text")
    root = Path(payload["root"])
    schema.require(
        root in roots.values() and root.resolve() == root,
        "Git root must exactly match a declared root",
    )
    return root
