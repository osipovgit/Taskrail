"""Freeze and attribute effective instructions independently of installed profiles."""

import json

from taskrail.core import prompt_texts
from taskrail.core.files import atomic_json, atomic_write, digest
from taskrail.core.schema import SCHEMAS, require

ROLES = ("understanding", "planner", "implementer", "reviewer")
CONTRACT = "00-input/contract.json"
TEXTS = "texts"


def validate_role_source(path):
    """Reject unreviewed role contracts before paying for source research."""
    source = path.read_bytes()
    require(
        "Instruction contract: 1." in source.decode("utf-8").splitlines(),
        f"Outdated role instructions: {path}. Use deploy/install.sh --agents=bundled "
        "or update the custom role against taskrail/agents/ before declaring Instruction contract: 1.",
    )
    return source


def capture(run, state, source):
    """Keep the complete role source, including custom templates, for this run."""
    state["agent_sources"] = {}
    state["agent_source_directory"] = str(source)
    for role in ROLES:
        source_bytes = validate_role_source(source / f"{role}.md")
        atomic_write(run / "00-input/agents" / f"{role}.md", source_bytes)
        state["agent_sources"][role] = digest(source_bytes)


def verify(run, state):
    """Changed frozen instructions cannot silently alter a continuation."""
    for role, expected in state.get("agent_sources", {}).items():
        source_bytes = validate_role_source(run / "00-input/agents" / f"{role}.md")
        if digest(source_bytes) != expected:
            raise ValueError("Saved agent instructions changed; restart required")


def freeze_contract(run, policy, state):
    """Only the first launch captures a contract; resumes retain those exact bytes.

    The contract holds the policy, every model-facing text and the response schemas;
    a continuation adopts its frozen texts.
    """
    path = run / CONTRACT
    if not path.exists():
        atomic_json(path, dict(policy=policy, texts=prompt_texts.release(), schemas=SCHEMAS))
    saved_bytes = path.read_bytes()
    signature = digest(saved_bytes)
    if state.get("contract_sha256", signature) != signature:
        raise ValueError("Saved instruction policy changed; restart required")
    state["contract_sha256"] = signature
    saved = json.loads(saved_bytes)
    if saved["schemas"] != SCHEMAS or saved[TEXTS] != prompt_texts.release():
        raise ValueError("Saved contract differs from this release; restart for fresh validation")
    prompt_texts.ACTIVE.adopt(saved[TEXTS])
    return saved


def adopt_texts(run):
    """Use the run's frozen texts, or this release's texts before the contract exists."""
    path = run / CONTRACT
    saved = json.loads(path.read_text()) if path.is_file() else {}
    if saved and saved[TEXTS] != prompt_texts.release():
        raise ValueError("Saved contract differs from this release; restart for fresh validation")
    prompt_texts.ACTIVE.adopt(saved.get(TEXTS) or prompt_texts.release())


def imported_draft(run, stage):
    """Old output can inform fresh research but cannot bypass the current contract."""
    path = run / "00-input/imported-response.raw.txt"
    if stage == "planner" and path.exists():
        return path.read_text(encoding="utf-8")
    return None
