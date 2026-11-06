"""Save the last usable context without executing a handoff as a request."""

from taskrail.application.feedback_files import context_json
from taskrail.core import prompt_texts
from taskrail.infrastructure.event_summary import decoded

STATUS = "status"
ENCODING = "utf-8"


def handoff(session, outcome, response):
    """Use remaining headroom for one summary; never dispatch a request from this turn."""
    target = session.active[0] / "handoff.md"
    # The executor may already have acted. Keep its entire response even if this turn dies.
    pending = dict(server_response=response, public_messages=prior_messages(target.parent))
    target.write_text(context_json(pending), encoding=ENCODING)
    from_task = prompt_texts.text("recovery.save")
    if not session.continue_context(outcome, from_task, handoff=True):
        return dict(outcome, status="SESSION_ERROR", errors=["Ambiguous handoff session"])
    session.launch["runtime"] = dict(
        session.launch.get("runtime", {}), context_budget=None, attached_files=()
    )
    saved = session.turn()
    if saved[STATUS] in {"SCOPE_VIOLATION", "SESSION_ERROR", "TIMEOUT"}:
        return saved
    if saved[STATUS] == "OK" and saved.get("final_text"):
        pending["session_notes"] = saved["final_text"]
        target.write_text(context_json(pending), encoding=ENCODING)
    saved[STATUS] = "CONTEXT_EXCEEDED"
    return saved


def preserve(folder, outcome):
    """Retain public text from a disconnected turn even if the provider cannot summarize."""
    if outcome[STATUS] not in {
        "CONTEXT_EXCEEDED",
        "TIMEOUT",
        "INCOMPLETE",
        "PROCESS_ERROR",
        "TURN_ERROR",
    }:
        return
    target = folder / "handoff.md"
    if target.exists():
        return
    messages = prior_messages(folder)
    if messages:
        target.write_text(context_json(messages), encoding=ENCODING)


def prior_messages(folder):
    """Read only the public parts already recorded before a context rotation."""
    events = folder / "events.jsonl"
    if not events.is_file():
        return []
    with events.open(encoding=ENCODING, errors="replace") as stream:
        return list(public_text(stream))


def public_text(stream):
    """Only opencode's public text parts may enter working notes."""
    for line in stream:
        event = decoded(line)
        if event and event.get("type") == "text":
            message = event.get("part", {}).get("text")
            if isinstance(message, str) and message.strip():
                yield message
