"""Public tool transcripts for server-executed operations in one stage."""

import json
import time
import uuid

MILLISECONDS = 1000
REJECTIONS = "rejections"
MAX_REJECTIONS = 20
REASON = 200


def write(folder, event):
    """Append one server-origin event without reporting invented token usage."""
    with (folder / "events.jsonl").open("a") as stream:
        stream.write(f"{json.dumps(event)}\n")


def begin(folder, name, arguments):
    """Expose pending execution immediately with a stable call identity."""
    stamp = int(time.time() * MILLISECONDS)
    identity = uuid.uuid4().hex
    event = dict(
        type="tool_use",
        timestamp=stamp,
        part=dict(
            id=identity,
            callID=identity,
            tool=name,
            state=dict(
                status="running",
                input=arguments,
                output="",
                time=dict(start=stamp),
                metadata=dict(origin="orchestrator"),
            ),
        ),
    )
    write(folder, event)
    return event


def finish(folder, event, output):
    """Complete the same tool call; nonzero command exits remain result data."""
    stamp = int(time.time() * MILLISECONDS)
    state = event["part"]["state"]
    state.update(status="completed", output=output)
    state["time"]["end"] = stamp
    event["timestamp"] = stamp
    write(folder, event)


def append(folder, name, arguments, output):
    """Publish an immediately available executor result."""
    event = begin(folder, name, arguments)
    finish(folder, event, output)


def correction(session, kind, response, feedback):
    """Publish a correction turn and remember why, for the stage record and analytics.

    kind names what was rejected: a final result, a request, an unavailable tool or an
    unread plan file; the reason is the first line of the feedback.
    """
    append(session.active[0], "correction", dict(response=response), feedback)
    reasons = session.context.setdefault(REJECTIONS, [])
    first = feedback.strip().partition("\n")[0]
    if len(reasons) < MAX_REJECTIONS:
        reasons.append(dict(kind=kind, reason=first[:REASON]))
