"""Prepare one model attempt: record, prompt, closed permission profile and allowance."""

from countersign.application import attempt_context, result_context
from countersign.application.artifacts import new_stage
from countersign.application.planned_paths import safe_file
from countersign.application.recovery import write_evidence
from countersign.infrastructure import artifact_access, opencode_api
from countersign.infrastructure.agent_sync import (
    atomic_write,
    make_profile,
    repair_mode,
    verify_permissions,
)

RECOVERY_NOTE = "\nRECOVERY: the preceding read-only attempt ended before a valid result. First read this recorded evidence file: {0}. It contains successful tool outputs, not conclusions. The source tree was checked unchanged. Do not restart broad discovery: reuse applicable evidence, read only missing ranges, and produce the final result. Truncated or omitted output is NOT complete evidence. Do not invent access failures without a tool error.\n"
ROLE = "role"
ROOTS = "roots"


def role_of(stage):
    """Plan review uses the reviewer role."""
    return "reviewer" if stage == "plan-reviewer" else stage


def open_record(workflow, mode):
    """Create the numbered stage record and reserve its durable budget."""
    stage = workflow.flow["stage"]
    role = role_of(stage)
    model = workflow.config["models"].get(role)
    active = new_stage(workflow.run, workflow.state, stage, role, mode, model=model)
    workflow.open_record(active)
    attempt_context.prepare(workflow.run, active[1], workflow.config, workflow.state)
    return active


def planned_files(workflow):
    """Approved files the current stage may write."""
    return [safe_file(name, workflow.config[ROOTS]) for name in workflow.writable()]


def attempt_prompt(workflow, active, request, recovery):
    """Add execution history and, for research recovery, the recorded evidence file."""
    history = result_context.execution_context(workflow.run, workflow.state)
    if not recovery:
        return f"{request}{history}"
    folder, record = active
    evidence_file = folder / "recovery.md"
    write_evidence(evidence_file, recovery)
    record["inputs"]["recovery"] = str(evidence_file.relative_to(workflow.run))
    record["recovery_source"] = recovery["source"]
    return "{0}{1}{2}".format(request, history, RECOVERY_NOTE.format(evidence_file))


def install_profile(workflow, active, files, format_only):
    """Write the closed opencode profile and verify that opencode enforces it."""
    folder, record = active
    base = permission_base(workflow.config, record, files)
    profile, permissions = make_profile(
        workflow.run / "00-input/agents" / f"{record[ROLE]}.md",
        workflow.config["destination"],
        agent_name(record),
        workflow.config[ROOTS].values(),
        artifact_access.model_inputs(workflow.run, folder),
        files,
        format_only=repair_mode(workflow.config, format_only),
        worktree=base,
    )
    workflow.runtime["profiles"].add(profile)
    atomic_write(folder / "agent.md", profile.read_bytes())
    verify_permissions(
        workflow.config["command"],
        next(iter(workflow.config[ROOTS].values())),
        agent_name(record),
        permissions,
        folder / "permissions.log",
    )
    return profile


def permission_base(config, record, files):
    """The base that relative permission patterns are written against."""
    base = opencode_api.relative_base(config, config[ROOTS], files)
    if base is not None:
        record["permission_worktree"] = str(base)
    return base


def agent_name(record):
    """Managed opencode profiles use stable role names."""
    return "countersign-{0}".format(record[ROLE])
