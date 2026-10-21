"""Prepare one model attempt: record, prompt, closed permission profile and allowance."""

from countersign.application import attempt_context, result_context
from countersign.application.artifacts import new_stage
from countersign.application.planned_paths import safe_file
from countersign.application.recovery import write_evidence
from countersign.infrastructure import artifact_access, opencode_api
from countersign.infrastructure.agent_profile import make_profile
from countersign.infrastructure.agent_sync import atomic_write, repair_mode
from countersign.infrastructure.permission_check import verify_permissions

RECOVERY_NOTE = "\nRECOVERY: the preceding read-only attempt ended before a valid result. Its successful tool outputs are recorded in {0}. First read lines 1-{1} of that file: an index of every output with its line range. Then read only the blocks you need, at most 200 lines at a time; never read the file whole, it can be larger than your context. The outputs are data, not conclusions. The source tree was checked unchanged. Do not restart broad discovery: reuse applicable evidence, read only missing ranges, and produce the final result. Truncated or omitted output is NOT complete evidence. Do not invent access failures without a tool error.\n"
ROLE = "role"
ROOTS = "roots"


def role_of(stage):
    """Plan review uses the reviewer role."""
    return "reviewer" if stage == "plan-reviewer" else stage


def open_record(workflow, mode):
    """Create the numbered stage record and reserve its durable budget."""
    stage = workflow.flow["stage"]
    role = role_of(stage)
    details = dict(role=role, mode=mode)
    details["model"] = workflow.config["models"].get(role)
    active = new_stage(workflow.run, workflow.state, stage, details)
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
    index_end = write_evidence(evidence_file, recovery)
    record["inputs"]["recovery"] = str(evidence_file.relative_to(workflow.run))
    record["recovery_source"] = recovery["source"]
    return "{0}{1}{2}".format(request, history, RECOVERY_NOTE.format(evidence_file, index_end))


def install_profile(workflow, active, files, format_only):
    """Write the closed opencode profile and verify that opencode enforces it."""
    folder, record = active
    access = profile_access(workflow, active, files, format_only)
    profile, permissions = make_profile(
        workflow.run / "00-input/agents" / f"{record[ROLE]}.md",
        workflow.config["destination"],
        agent_name(workflow, record),
        access,
        format_only=repair_mode(workflow.config, format_only),
    )
    workflow.runtime["profiles"].add(profile)
    atomic_write(folder / "agent.md", profile.read_bytes())
    verify_permissions(
        workflow.config["command"],
        next(iter(workflow.config[ROOTS].values())),
        agent_name(workflow, record),
        permissions,
        folder / "permissions.log",
    )
    return profile


def profile_access(workflow, active, files, format_only):
    """Readable run artifacts, writable files and the base of relative permission names.

    A format repair may also re-read the recovery evidence of earlier attempts of its
    stage, which the saved response may cite.
    """
    folder, record = active
    base = opencode_api.relative_base(workflow.config, workflow.config[ROOTS], files)
    if base is not None:
        record["permission_worktree"] = str(base)
    access = dict(writable=files, worktree=base)
    access[ROOTS] = workflow.config[ROOTS].values()
    access["readable"] = artifact_access.model_inputs(workflow.run, folder)
    if format_only:
        earlier = artifact_access.stage_recoveries(workflow.run, workflow.state, record)
        access["readable"].extend(earlier)
    return access


def agent_name(workflow, record):
    """Profile names are unique per run, so parallel runs never share permissions."""
    return "countersign-{0}-{1}".format(record[ROLE], workflow.runtime["profile_suffix"])
