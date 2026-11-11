"""Freeze and attribute effective instructions independently of installed profiles."""

import json
from pathlib import Path

from taskrail.core import prompt_texts
from taskrail.core.files import atomic_write, bounded_bytes, digest
from taskrail.core.schema import SCHEMAS, require

ROLES = ("understanding", "planner", "implementer", "reviewer")
BUNDLED_AGENTS = Path(__file__).resolve().parents[1] / "agents"
CONTRACT = "00-input/contract.json"
SIGNATURE = "contract_sha256"
POLICY = Path(__file__).with_name("policy.md").read_text(encoding="utf-8")
CONTRACT_BYTES = (
    json.dumps(
        dict(policy=POLICY, texts=dict(prompt_texts.ENTRIES), schemas=SCHEMAS),
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
).encode()
CONTRACT_DIGEST = digest(CONTRACT_BYTES)


def role_directory(options, base):
    """Resolve the configured role directory relative to its settings file."""
    return base / Path(options.get("agent_source", BUNDLED_AGENTS)).expanduser()


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
    """Capture the build contract and operator-selected role sources for a new run."""
    atomic_write(run / CONTRACT, CONTRACT_BYTES)
    state[SIGNATURE] = CONTRACT_DIGEST
    state["agent_sources"] = {}
    state["agent_source_directory"] = str(source)
    for role in ROLES:
        source_bytes = validate_role_source(source / f"{role}.md")
        atomic_write(run / "00-input/agents" / f"{role}.md", source_bytes)
        state["agent_sources"][role] = digest(source_bytes)


def verify(run, state):
    """Changed frozen instructions cannot silently alter a continuation."""
    verify_contract(run, state)
    sources = state.get("agent_sources")
    require(
        isinstance(sources, dict) and sources.keys() == set(ROLES),
        "Incomplete role fingerprints; restart required",
    )
    for role, expected in sources.items():
        source_bytes = validate_role_source(run / "00-input/agents" / f"{role}.md")
        if digest(source_bytes) != expected:
            raise ValueError("Saved agent instructions changed; restart required")


def verify_contract(run, state):
    """The recorded seal and saved bytes must both match the active build."""
    require(
        state.get(SIGNATURE) == CONTRACT_DIGEST
        and bounded_bytes(run / CONTRACT, len(CONTRACT_BYTES)) == CONTRACT_BYTES,
        "Saved instruction contract changed or is missing; restart required",
    )


def imported_draft(run, stage):
    """Old output can inform fresh research but cannot bypass the current contract."""
    path = run / "00-input/imported-response.raw.txt"
    if stage == "planner" and path.exists():
        return path.read_text(encoding="utf-8")
    return None
