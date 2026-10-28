"""Mode instructions from the run's task header flags, for browser and CLI tasks alike.

A run that changes code plans its Goal as tasks in plan.md. With Decision single the
same run implements them; with Decision split each task becomes its own run (see
plan_contract.splits), implemented in plan order directly from the reviewed plan.
Checks that must run after the change are listed under `## After the change` with fixed
prefixes, so the server can run Jenkins validation and, after the operator confirms,
server checks. On a Taskrail branch the implementer may go beyond the planned files
and the reviewer judges what it changed beyond them. The texts live in
core/prompt-texts.json.
"""

from types import MappingProxyType

from taskrail.core.prompt_texts import text

PLANNING_STAGES = frozenset(("planner", "plan-reviewer"))
PLANNER = "planner"
DELIVERY_REVIEW = "mode.delivery.review"
# A delivery phase's rule; check phases apply theirs to the stages after planning.
PHASE_RULES = MappingProxyType(
    {"integration": "mode.integration", "validation": DELIVERY_REVIEW, "server": DELIVERY_REVIEW}
)
# Mode flag -> its rule for the planner; reviewing stages use the rule's .review form.
READ_ONLY_FLAGS = MappingProxyType({"design": "mode.design", "read_only": "mode.answer"})
PLANNING_RULES = frozenset(("mode.change", "mode.decompose"))
# Stages of a run with a writer whose rules change on a Taskrail branch.
BRANCH_STAGES = frozenset(("implementer", "reviewer"))
WRITING_PHASES = frozenset((None, "task"))


def render(config, stage):
    """The rule of the run's mode for one stage; an empty string when none applies."""
    rule = mode_rule(config, stage)
    if not branch(config, stage):
        return rule
    return "\n".join(filter(None, (rule, text(f"mode.branch.{stage}"))))


def branch(config, stage):
    """A writing stage, or its review, on a Taskrail branch."""
    writing = config.get("phase") in WRITING_PHASES
    return writing and stage in BRANCH_STAGES and config.get("task_branch") is True


def mode_rule(config, stage):
    """The rule of the run's mode itself."""
    if config.get("phase") == "task":
        return task_rule(config, stage)
    key = mode_key(config, stage)
    if key in PLANNING_RULES:
        return planning_rule(key)
    return text(key) if key else ""


def mode_key(config, stage):
    """The catalog key of the rule, or None."""
    phase = config.get("phase")
    if phase in PHASE_RULES and (phase == "integration" or stage != PLANNER):
        return PHASE_RULES[phase]
    if config.get("decompose"):
        return "mode.decompose"
    flag = next((name for name in READ_ONLY_FLAGS if config.get(name)), None)
    if flag:
        suffix = "" if stage == PLANNER else ".review"
        return READ_ONLY_FLAGS[flag] + suffix
    return "mode.change" if stage in PLANNING_STAGES else None


def planning_rule(key):
    """A code change: the mode, what a task is and the checks after the change."""
    return "\n".join((text(key), text("mode.tasks"), text("mode.checks")))


def task_rule(config, stage):
    """One task of a reviewed split: its implementer or reviewer; it is never planned again."""
    key = f"mode.task.{stage}"
    if stage == "implementer" and config.get("task_branch") is True:
        key = f"{key}.branch"
    return text(key, task=config["assigned_contract"]["task_id"])
