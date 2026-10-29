"""The implementer's result: DONE or BLOCKED with a few words; the rest is observed.

The implementer keeps its progress in progress.md and ends with `DONE: <what changed>`
or `BLOCKED: <what it needs>`. The server takes the changed files from its source scan
and the checks from their records; the independent review judges every requirement,
so the implementer reports no requirement outcomes or citations.
"""

import re

from taskrail.core import prompt_texts

FINAL = re.compile(r"^[\s>*_`#-]*(DONE|BLOCKED)\b[\s*_`]*:?[\s*_`]*(.*)$", re.IGNORECASE)
BLOCKED = "BLOCKED"


def stage_result(response, context):
    """The canonical implementation record of a final DONE or BLOCKED message."""
    word, text = final_word(response)
    record = dict(schema_version=1, coverage=[], evidence=[], unverified=[])
    record.update(changed_files=context["changed"])
    if word == BLOCKED:
        return dict(record, **blocked(text))
    return dict(record, **finished(text, context))


def blocked(text):
    """A blocked implementation: its reason is the one blocking gap."""
    reason = text or prompt_texts.text("implementer.blocked")
    return dict(status=BLOCKED, summary=reason, blocking_gaps=[reason], completed_steps=[])


def finished(text, context):
    """A finished implementation completes every approved step."""
    steps = (context.get("plan") or {}).get("steps", [])
    summary = text or prompt_texts.text("implementer.done")
    completed = [step["id"] for step in steps]
    return dict(status="IMPLEMENTED", summary=summary, blocking_gaps=[], completed_steps=completed)


def final_word(response):
    """The last DONE or BLOCKED line and the text after it; ValueError without one."""
    lines = response.strip().splitlines()
    for index in range(len(lines) - 1, -1, -1):
        found = FINAL.match(lines[index])
        if found:
            following = lines[index + 1 :]
            text = " ".join([found.group(2), *following])
            return found.group(1).upper(), " ".join(text.split())
    raise ValueError(prompt_texts.text("implementer.missing"))
