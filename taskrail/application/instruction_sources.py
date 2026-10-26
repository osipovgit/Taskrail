"""Freeze and attribute effective instructions independently of installed profiles."""

import hashlib
import json

from taskrail.core import prompt_texts
from taskrail.core.files import atomic_json
from taskrail.core.schema import SCHEMAS, require
from taskrail.infrastructure.agent_sync import atomic_write

ROLES = ("planner", "implementer", "reviewer")
CONTRACT = "00-input/contract.json"


def validate_role_source(path):
    """Reject unreviewed role contracts before paying for source research."""
    require(
        "Instruction contract: 1." in path.read_text(encoding="utf-8").splitlines(),
        f"Outdated role instructions: {path}. Use deploy/install.sh --agents=bundled "
        "or update the custom role against taskrail/agents/ before declaring Instruction contract: 1.",
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


def freeze_contract(run, policy, state):
    """Only the first launch captures a contract; resumes retain those exact bytes.

    The contract holds the policy, every model-facing text and the response schemas;
    a continuation adopts its frozen texts.
    """
    path = run / CONTRACT
    if not path.exists():
        atomic_json(path, dict(policy=policy, texts=prompt_texts.release(), schemas=SCHEMAS))
    signature = fingerprint(path.read_bytes())
    if state.get("contract_sha256", signature) != signature:
        raise ValueError("Saved instruction policy changed; restart required")
    state["contract_sha256"] = signature
    saved = json.loads(path.read_text())
    if saved["schemas"] != SCHEMAS or "texts" not in saved:
        raise ValueError("Saved contract differs from this release; restart for fresh validation")
    prompt_texts.ACTIVE.adopt(saved["texts"])
    return saved


def adopt_texts(run):
    """Use the run's frozen texts, or this release's texts before the contract exists."""
    path = run / CONTRACT
    saved = json.loads(path.read_text()) if path.is_file() else {}
    prompt_texts.ACTIVE.adopt(saved.get("texts") or prompt_texts.release())


def imported_draft(run, stage):
    """Old output can inform fresh research but cannot bypass the current contract."""
    path = run / "00-input/imported-response.raw.txt"
    if stage == "planner" and path.exists():
        return path.read_text(encoding="utf-8")
    return None
