"""Compose one effective instruction contract for each workflow stage.

A request has three parts: the task with its requirement labels, the instructions this
stage needs (its policy sections, stage and mode, instruction modules, executor routes
and response format) and the Context JSON. Every model-facing text comes from the
frozen policy and prompt catalog.
"""

from taskrail.application import (
    execution_requests,
    instruction_modules,
    instruction_sources,
    mode_rules,
    policy_sections,
    response_format,
    task_block,
    workspace_paths,
)
from taskrail.application.context_projection import request_context, task_text
from taskrail.application.feedback_files import context_json
from taskrail.application.understanding_prompt import request as understand
from taskrail.core import prompt_texts

INSTRUCTIONS_HEADING = "# Orchestrator instructions"


def make_request(config, execution, state, run):
    """The complete request of one stage attempt."""
    instruction_sources.verify_contract(run, state)
    stage = execution[0]
    if stage == "understanding":
        return understand(config, execution, state, run, instruction_sources.POLICY)
    catalog = execution_requests.available()
    if not catalog.get("unavailable"):
        state["jenkins_configured"] = bool(catalog.get("jenkins"))
    task = task_text(config, run, state.get("requirements", []))
    parts = (
        policy_sections.for_stage(instruction_sources.POLICY, stage),
        prompt_texts.text(f"stage.{stage}"),
        workspace_paths.instructions(config),
        task_block.render(config, execution),
        mode_rules.render(config, stage),
        instruction_modules.render(run, execution, state),
        prompt_texts.text("understanding.revision")
        if stage in {"planner", "plan-reviewer"} and not config.get("phase")
        else "",
        response_format.section(stage, run, config, catalog),
        f"Context:\n{context_json(request_context(config, execution, state, run))}",
    )
    return "# Task\n{}\n\n{}\n{}".format(
        task, INSTRUCTIONS_HEADING, "\n\n".join(filter(None, parts))
    )
