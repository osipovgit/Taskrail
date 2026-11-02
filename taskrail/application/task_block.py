"""The approved task of a single run, as Markdown at the top of its implementer request.

The plan also reaches the implementer as Context JSON; a weak model finds its work more
reliably in a short block it can read like the plan file. A task of a split already
carries its contract in the task text, so only an ordinary run gets this block.
"""

from taskrail.core.prompt_texts import text

IMPLEMENTER = "implementer"


def render(config, execution):
    """The block for an implementer of an ordinary run with one approved task, else ""."""
    stage, plan = execution[0], execution[1] or {}
    steps = plan.get("steps", [])
    if stage != IMPLEMENTER or config.get("phase") or len(steps) != 1:
        return ""
    step = steps[0]
    return text(
        "implementer.task",
        title=step.get("title") or step.get("action", ""),
        files=bullets(step.get("files", [])),
        done=bullets(step.get("done_when", [])),
        checks=bullets(step.get("checks", [])),
        required=bullets(step.get("required_checks", [])),
        notes=step.get("notes") or "none",
    )


def bullets(entries):
    """One bullet per entry, or `- none`."""
    return "\n".join(f"- {entry}" for entry in entries) or "- none"
