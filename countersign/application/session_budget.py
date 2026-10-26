"""Conservative admission estimates, separate from cumulative provider usage."""

from pathlib import Path

from countersign.application import context_windows, evidence, source_packet
from countersign.application.planned_paths import safe_file
from countersign.core.paths import readable_source
from countersign.infrastructure import agent_profile
from countersign.infrastructure.context_overflow import STATUS

BYTES_PER_TOKEN = 1
FRAMING_TOKENS = 1024


def admission(config, active, files):
    """Refuse an oversized request for any role before spending a model turn."""
    folder, record = active
    estimate = measured(config, folder, files, record)
    record["context_budget"] = estimate
    if estimate["estimated_input_tokens"] < estimate["input_capacity_tokens"]:
        return None
    reason = (
        "{role} admission exceeds the reserved context boundary: "
        "{estimated_input_tokens} estimated input tokens, {input_capacity_tokens} available. "
        "Split this task or narrow the approved input files before retrying; increase "
        "model_context_tokens only when the selected model supports the larger window."
    ).format(role=record["role"].capitalize(), **estimate)
    return dict(
        status=STATUS,
        errors=[reason],
        final_text="",
        completed=False,
        tokens={},
        elapsed_seconds=0,
        usage_complete=False,
        admission_blocked=True,
    )


def plan_inputs(plan, roots, role="implementer"):
    """Count read dependencies and edit targets through their existing scope validators."""
    if role != "implementer" or not plan:
        return []
    edits = plan.get("proposed_change_files", [])
    paths = [safe_file(name, roots) for name in edits]
    for name in plan.get("files_read", []):
        if name not in edits:
            paths.append(readable_source(name, roots))
    return sorted(set(paths))


def measured(config, folder, files, record):
    """Estimate UTF-8 input bytes without relying on a provider-specific tokenizer.

    The stage record names the role, whose model chooses the context window.
    """
    stage = record.get("stage", record["role"])
    existing = [path for path in set(map(Path, files)) if path.is_file()]
    role = agent_profile.body(folder / "agent.md")
    request = folder / "request.md"
    sizes = dict(
        request_bytes=request.stat().st_size if request.exists() else 0,
        role_bytes=len(role.encode("utf-8")),
        planned_input_bytes=planned_bytes(folder, existing, stage),
    )
    return dict(
        sizes,
        bytes_per_token=BYTES_PER_TOKEN,
        framing_tokens=FRAMING_TOKENS,
        estimated_input_tokens=sum(sizes.values()) + FRAMING_TOKENS,
        input_capacity_tokens=context_windows.role_capacity(config, record["role"]),
    )


def planned_bytes(folder, existing, stage):
    """Charge every approved input, subtracting only exact already-delivered text bytes."""
    target = source_packet.location(folder.parent, stage)
    packet = source_packet.packet_index(target).values()
    totals = []
    for path in existing:
        unread = path.stat().st_size - delivered_bytes(path, packet)
        totals.append(max(0, unread))
    return sum(totals)


def delivered_bytes(path, packet):
    """A partial window cannot exempt its unread suffix or unrelated approved files."""
    visible = {}
    fingerprint = evidence.fingerprint(path)
    for entry in packet:
        matches = entry["path"] == str(path)
        matches = matches and entry["source_sha256"] == fingerprint
        if matches:
            visible.update(entry["lines"])
    return sum(len(line.encode("utf-8")) for line in visible.values())
