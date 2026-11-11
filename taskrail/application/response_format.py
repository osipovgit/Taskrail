"""Stage submissions and one copyable example per available executor."""

import json
from types import MappingProxyType

from taskrail.application import execution_requests, plan_file, progress_file, review_file
from taskrail.core import protected_paths
from taskrail.core.prompt_texts import text
from taskrail.git import requests as git_requests
from taskrail.interactions import local

PLANNER = "planner"
IMPLEMENTER = "implementer"


FINISHES = MappingProxyType(
    {
        "understanding": "format.understanding_finish",
        PLANNER: "format.plan_finish",
        IMPLEMENTER: "format.done_finish",
        "plan-reviewer": "format.review_finish",
        "reviewer": "format.review_finish",
    }
)


def finish(stage):
    """The stage's final-result instruction, shared by continuations and corrections."""
    return text(FINISHES[stage])


def continuation(stage, request):
    """Resume the current task with the same output contract as its first turn."""
    resumed = text("format.continuation", stage=stage, request=request, finish=finish(stage))
    return f"\n{resumed}\n"


def correction(stage, error):
    """Correct a rejected result; the continuation that follows restates the format."""
    return "{}\n".format(text("format.correction", error=error))


def section(stage, run, config, catalog):
    """Show the stage submission, then the route rules beside their examples."""
    if stage == PLANNER:
        rules = plan_file.instructions(run, config["roots"], protected_paths.patterns(config))
        routing = text("format.plan_routing")
    elif stage == IMPLEMENTER:
        rules = "\n".join((progress_file.instructions(run), text("format.done")))
        routing = text("format.request_routing")
    else:
        rules = review_file.instructions(run, stage)
        routing = text("format.request_routing")
    working_root = next(iter(config["roots"].values()))
    root = json.dumps(str(working_root), ensure_ascii=False)
    lines = (
        rules,
        routing,
        git_requests.instructions(stage, config.get("task_branch", False)),
        text("example.git", root=root),
        local.instructions(
            stage, config.get("host_commands", "auto"), config.get("sandbox_network") is True
        ),
        text("example.local", root=root),
        execution_requests.instructions(config, stage, run, catalog),
    )
    return "\n".join(filter(None, lines))
