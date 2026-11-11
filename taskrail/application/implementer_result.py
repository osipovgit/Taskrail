"""The implementer's result: DONE or BLOCKED with a few words; the rest is observed.

The implementer keeps its progress in progress.md and ends with `DONE: <what changed>`
or `BLOCKED: <what it needs>`. The server takes the changed files from its source scan
and the checks from their records; the independent review judges every requirement,
so the implementer reports no requirement outcomes or citations.
"""

from taskrail.core import prompt_texts, reply_frame, schema


def stage_result(response, context):
    """The canonical implementation record of a final DONE or BLOCKED message."""
    word, text = final_word(response)
    record = dict(schema_version=1, coverage=[], evidence=[], unverified=[])
    record.update(changed_files=context["changed"])
    if word == reply_frame.BLOCKED:
        return dict(record, **blocked(text))
    return dict(record, **finished(text, context))


def blocked(text):
    """A blocked implementation: its reason is the one blocking gap."""
    reason = text or prompt_texts.text("implementer.blocked")
    return dict(
        status=reply_frame.BLOCKED, summary=reason, blocking_gaps=[reason], completed_steps=[]
    )


def finished(text, context):
    """A finished implementation completes every approved step."""
    steps = (context.get("plan") or {}).get("steps", [])
    if not context["changed"]:
        schema.require(bool(text), prompt_texts.text("implementer.no_change"))
    summary = text or prompt_texts.text("implementer.done")
    completed = [step["id"] for step in steps]
    return dict(status="IMPLEMENTED", summary=summary, blocking_gaps=[], completed_steps=completed)


def final_word(response):
    """The last DONE or BLOCKED line and the text after it; ValueError without one."""
    lines = response.strip().splitlines()
    for index in range(len(lines) - 1, -1, -1):
        found = reply_frame.final_line(lines[index])
        if found:
            following = lines[index + 1 :]
            text = "\n".join([found[1], *following])
            return found[0], text.strip()
    raise ValueError(prompt_texts.text("implementer.missing"))
