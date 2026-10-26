"""Source changes made by approved local commands: adopted, journaled and reported.

The operator approved the exact command, so its effects become part of the source
instead of stopping the run. Files Git ignores (caches, reports) are not source at all.
The session is told about changed files it may not edit; Git metadata changed outside
the controlled executor still stops the run.
"""

from taskrail.core import prompt_texts, schema
from taskrail.core.files import changed
from taskrail.core.paths import tool_paths
from taskrail.git import dispatch
from taskrail.interactions import local_journal

GIT_CHANGED = "Git metadata changed outside the controlled executor; stopped without rollback"
SOURCE_EFFECT = "source_effect"


def adopt(session, action_id):
    """Adopt what an executed command changed; feedback names files outside the scope."""
    environment = session.environment
    current = environment["scan"]()
    unchanged = environment["git_metadata"](environment["roots"]) == environment["git_before"]
    schema.require(unchanged, GIT_CHANGED)
    delta = changed(environment["expected"], current)
    if not delta:
        return ""
    environment["expected"] = current
    session.state[SOURCE_EFFECT] = (current, environment["git_before"])
    dispatch.checkpoint(environment["run"], current, environment["git_before"])
    record(session, action_id, delta)
    return feedback(session, delta)


def record(session, action_id, delta):
    """Keep the changed files in the run state and in the action's journal entry."""
    effects = session.state.setdefault("command_effects", [])
    stage = session.active[0].name
    effects.append(dict(action_id=action_id, stage=stage, files=delta))
    local_journal.record_effects(session.environment["run"], action_id, delta)


def feedback(session, delta):
    """What the session must know: changed files that are not its own to edit."""
    writer = session.active[1]["role"] == "implementer"
    allowed = set(session.environment["allowed"]) if writer else set()
    outside = [name for name in delta if name not in allowed]
    if not outside:
        return ""
    rule = "feedback.command_effects.{}".format("writer" if writer else "read_only")
    files = ", ".join(tool_paths(outside, session.environment["roots"]))
    return prompt_texts.text("feedback.command_effects", files=files, rule=prompt_texts.text(rule))
