"""Compose one effective instruction contract for each workflow stage.

A request has three parts: the task with its requirement labels, the instructions this
stage needs (its policy sections, stage and mode, instruction modules, executor routes
and response format) and the Context JSON. Every model-facing text comes from the
frozen policy and prompt catalog.
"""

import json
from pathlib import Path
from types import MappingProxyType

from taskrail.application import (
    execution_requests,
    instruction_modules,
    instruction_sources,
    mode_rules,
    plan_file,
    policy_sections,
    response_format,
)
from taskrail.application.context_projection import request_context, task_text
from taskrail.core import prompt_texts, schema
from taskrail.git import requests as git_requests
from taskrail.interactions import local

CONTEXT_LINE_LIMIT = 800
CHUNK_SIZE = 500
POLICY = Path(__file__).with_name("policy.md").read_text()
INSTRUCTIONS_HEADING = "# Orchestrator instructions"
ROLE_SCHEMAS = MappingProxyType({"planner": "planner", "implementer": "implementer-decision"})


def readable_context(payload):
    """Preserve complete text without exceeding opencode's per-line read limit."""
    if isinstance(payload, str) and len(payload) > CONTEXT_LINE_LIMIT:
        offsets = range(0, len(payload), CHUNK_SIZE)
        chunks = [payload[offset : offset + CHUNK_SIZE] for offset in offsets]
        return {"text_chunks": chunks}
    if isinstance(payload, dict):
        return {key: readable_context(entry) for key, entry in payload.items()}
    if isinstance(payload, list):
        return [readable_context(entry) for entry in payload]
    return payload


def context_json(payload):
    """Context as JSON with one-space indentation: one value per line, few spaces."""
    return json.dumps(readable_context(payload), ensure_ascii=False, indent=1)


def saved_response_prompt(text):
    return context_json({"saved_response": text})


def make_request(config, execution, state, run):
    """The complete request of one stage attempt."""
    state["module_source_files"] = instruction_modules.observed_files(run)
    frozen = instruction_sources.freeze_contract(run, POLICY, state)
    stage = execution[0]
    catalog = execution_requests.available()
    task = task_text(config, run, state.get("requirements", []))
    parts = (
        policy_sections.for_stage(frozen["policy"], stage),
        prompt_texts.text(f"stage.{stage}"),
        mode_rules.render(config, stage),
        instruction_modules.render(run, execution, state),
        execution_requests.instructions(config, stage, run, catalog),
        git_requests.instructions(stage),
        local.instructions(stage),
        response_format.section(stage, state, run, config, catalog),
        f"Context:\n{context_json(request_context(config, execution, state, run))}",
    )
    return "# Task\n{}\n\n{}\n{}".format(
        task, INSTRUCTIONS_HEADING, "\n\n".join(filter(None, parts))
    )


def contract(stage, version):
    """Publish the same schema used by validation, rather than a second example."""
    schema.contract_version(version)
    role = "reviewer" if stage == "plan-reviewer" else stage
    selected = ROLE_SCHEMAS.get(role, "decision")
    return json.dumps(schema.SCHEMAS[selected], ensure_ascii=False, separators=(",", ":"))


def repair(response, error, stage, version, requirements):
    """Conversion cannot inherit research directives or introduce new evidence.

    Requirements appear under the same R<n> labels as in the stage request.
    """
    return "\n".join(
        (
            prompt_texts.text("repair.header"),
            repair_rules(stage),
            prompt_texts.text("repair.error", error=plan_file.labelled(error, requirements)),
            prompt_texts.text("repair.schema"),
            contract(stage, version),
            prompt_texts.text("repair.requirements"),
            context_json(plan_file.labelled_requirements(requirements)),
            saved_response_prompt(response),
        )
    )


def repair_rules(stage):
    """The decision rules of the stage; a writer cannot edit during a repair."""
    rules = response_format.decisions(stage)
    if stage == "implementer":
        return "{}\n{}".format(rules, prompt_texts.text("repair.implementer"))
    return rules
