"""Prepare one model attempt: record, prompt, closed permission profile and allowance."""

from pathlib import Path

from taskrail.application import (
    attempt_context,
    context_handoff,
    followup_selection,
    result_context,
)
from taskrail.application.artifacts import new_stage
from taskrail.application.planned_paths import git_files, writable_roots
from taskrail.application.recovery import write_evidence
from taskrail.core import prompt_texts, protected_paths
from taskrail.infrastructure import artifact_access, opencode_api
from taskrail.infrastructure.agent_profile import make_profile
from taskrail.infrastructure.agent_sync import atomic_write
from taskrail.infrastructure.permission_check import verify_launch

ROLE = "role"
ROOTS = "roots"


def role_of(stage):
    """Plan review uses the reviewer role."""
    return "reviewer" if stage == "plan-reviewer" else stage


def open_record(workflow, mode):
    """Create the numbered stage record with its remaining active time."""
    stage = workflow.flow["stage"]
    role = role_of(stage)
    details = dict(role=role, mode=mode)
    details["model"] = workflow.config["models"].get(role)
    active = new_stage(workflow.run, workflow.state, stage, details)
    workflow.open_record(active)
    attempt_context.prepare(workflow.run, active[1], workflow.config, workflow.state)
    active[1]["timeout_seconds"] = attempt_context.remaining(workflow, stage)
    return active


def planned_files(workflow):
    """Approved files the current stage may write; on a task branch, its whole roots."""
    files = git_files(workflow)
    return [*files, *writable_roots(workflow.config, files)]


def attempt_prompt(workflow, active, request, recovery):
    """Add execution history and, for research recovery, the recorded evidence file."""
    history = result_context.execution_context(workflow.run, workflow.state)
    history += context_handoff.prior_handoff(workflow.state["stages"], workflow.run)
    if not recovery:
        return f"{request}{history}"
    folder, record = active
    evidence_file = folder / "recovery.md"
    index_end = write_evidence(evidence_file, recovery)
    record["inputs"]["recovery"] = str(evidence_file.relative_to(workflow.run))
    record["recovery_source"] = recovery["source"]
    return "{}{}\n{}\n".format(
        request, history, prompt_texts.text("recovery.evidence", file=evidence_file, end=index_end)
    )


def install_profile(workflow, active, files):
    """Write the closed opencode profile and verify that opencode enforces it."""
    folder, record = active
    access = profile_access(workflow, active, files)
    profile, permissions = make_profile(
        workflow.run / "00-input/agents" / f"{record[ROLE]}.md",
        workflow.config["destination"],
        agent_name(workflow, record),
        access,
    )
    workflow.runtime["profiles"].add(profile)
    atomic_write(folder / "agent.md", profile.read_bytes())
    verify_launch(
        dict(workflow.config, stop_run=workflow.run),
        next(iter(workflow.config[ROOTS].values())),
        agent_name(workflow, record),
        permissions,
        folder / "permissions.log",
    )
    return profile


def profile_access(workflow, active, files):
    """Readable run artifacts, writable files and the base of relative permission names."""
    folder, record = active
    base = opencode_api.relative_base(workflow.config, workflow.config[ROOTS], files)
    if base is not None:
        record["permission_worktree"] = str(base)
    writable = list(map(Path, record["writable_files"]))
    access = dict(writable=writable, worktree=base)
    if workflow.writable():
        access["preserved"] = followup_selection.paths(workflow, followup_selection.PRESERVED)
    access["protected"] = protected_paths.patterns(workflow.config)
    access[ROOTS] = workflow.config[ROOTS].values()
    access["readable"] = artifact_access.model_inputs(workflow.run, folder)
    access["readable"].extend(map(Path, record.get("attached_files", ())))
    return access


def agent_name(workflow, record):
    """Profile names are unique per run, so parallel runs never share permissions."""
    return "taskrail-{}-{}".format(record[ROLE], workflow.runtime["profile_suffix"])
