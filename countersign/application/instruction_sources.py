"""Freeze and attribute effective instructions independently of installed profiles."""

import hashlib
import json

from countersign.core.files import atomic_json
from countersign.core.schema import SCHEMAS, require
from countersign.infrastructure.agent_sync import atomic_write

ROLES = ("planner", "implementer", "reviewer")


def validate_role_source(path):
    """Reject unreviewed role contracts before paying for source research."""
    require(
        "Instruction contract: 1." in path.read_text(encoding="utf-8").splitlines(),
        f"Outdated role instructions: {path}. Use deploy/install.sh --agents=bundled "
        "or update the custom role against countersign/agents/ before declaring Instruction contract: 1.",
    )


def fingerprint(source_bytes):
    """A source_bytes identity does not depend on role filenames or release labels."""
    return hashlib.sha256(source_bytes).hexdigest()


def capture(run, state, source):
    """Keep the complete role source, including custom templates, for this run."""
    state["agent_sources"] = {}
    state["agent_source_directory"] = str(source)
    for role in ROLES:
        validate_role_source(source / f"{role}.md")
        source_bytes = (source / f"{role}.md").read_bytes()
        atomic_write(run / "00-input/agents" / f"{role}.md", source_bytes)
        state["agent_sources"][role] = fingerprint(source_bytes)


def verify(run, state):
    """Changed frozen instructions cannot silently alter a continuation."""
    for role, expected in state.get("agent_sources", {}).items():
        validate_role_source(run / "00-input/agents" / f"{role}.md")
        source_bytes = (run / "00-input/agents" / f"{role}.md").read_bytes()
        if fingerprint(source_bytes) != expected:
            raise ValueError("Saved agent instructions changed; restart required")


def freeze_contract(run, policy, instructions, state):
    """Only the first launch captures a contract; resumes retain those exact bytes."""
    path = run / "00-input/contract.json"
    if not path.exists():
        atomic_json(path, {"policy": policy, "instructions": instructions, "schemas": SCHEMAS})
    signature = fingerprint(path.read_bytes())
    if state.get("contract_sha256", signature) != signature:
        raise ValueError("Saved instruction policy changed; restart required")
    state["contract_sha256"] = signature
    saved = json.loads(path.read_text())
    if saved["schemas"] != SCHEMAS:
        raise ValueError("Saved contract differs from this release; restart for fresh validation")
    return saved


def imported_draft(run, stage):
    """Old output can inform fresh research but cannot bypass the current contract."""
    path = run / "00-input/imported-response.raw.txt"
    if stage == "planner" and path.exists():
        return path.read_text(encoding="utf-8")
    return None
