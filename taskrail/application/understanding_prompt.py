"""Deliver original task fields to interpretation without a source-research packet."""

from taskrail.application import history_file, policy_sections, understanding_file
from taskrail.application.context_projection import feedback_context
from taskrail.application.feedback_files import context_json
from taskrail.core import prompt_texts, requirements


def request(config, execution, state, run, policy):
    """The first stage receives full input and repair feedback, never inferred file ownership."""
    context = dict(
        stage=understanding_file.STAGE,
        roots=state["roots"],
        task_file=str(run / "00-input/task.md"),
        task_fields=config["task_spec"]["fields"],
        feedback=feedback_context(execution[3]),
    )
    state["instruction_modules"] = []
    sections = (
        policy_sections.for_stage(policy, understanding_file.STAGE),
        prompt_texts.text("stage.understanding"),
        understanding_file.instructions(run),
        f"Context:\n{context_json(context)}",
    )
    _, marker, historical = config["task_text"].partition(requirements.HISTORY)
    task = prompt_texts.text("understanding.task") + marker + historical
    return "# Task\n{}\n\n# Orchestrator instructions\n{}".format(
        history_file.prompt_task(task, run), "\n\n".join(sections)
    )
