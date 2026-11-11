"""Reserve one model message before handing it to any effectful executor."""

import json

from taskrail.core import prompt_texts
from taskrail.core.files import atomic_json, digest


def receipt_path(run, outcome):
    """Use the provider's final assistant message, independent of a worker or turn counter."""
    sessions = outcome.get("sessions", [])
    message = outcome.get("final_message_id")
    if len(sessions) != 1 or not message:
        return None
    identity = digest(json.dumps([sessions[0], message]).encode())
    directory = run / "executor-deliveries"
    directory.mkdir(exist_ok=True)
    return directory / f"{identity}.json"


def route(actions, outcome, kind, payload, dispatch):
    """A redelivered message can return its answer, even after the worker restarted."""
    receipt = receipt_path(actions.session.environment["run"], outcome)
    if receipt is None:
        return prompt_texts.text("feedback.dispatch_identity")
    encoded = json.dumps([actions.folder.name, kind, payload], sort_keys=True)
    operation = digest(encoded.encode())
    try:
        receipt.touch(exist_ok=False)
    except FileExistsError:
        return recorded(receipt, operation, outcome)
    atomic_json(receipt, dict(operation=operation))
    response = dispatch(actions, outcome, kind, payload)
    status = {key: outcome[key] for key in ("status", "errors") if key in outcome}
    atomic_json(receipt, dict(operation=operation, response=response, outcome=status))
    return response


def recorded(receipt, operation, outcome):
    """A crash even before completing the exclusive reservation leaves the action held."""
    try:
        entry = json.loads(receipt.read_text())
    except ValueError:
        return prompt_texts.text("feedback.dispatch_interrupted")
    if entry["operation"] != operation:
        outcome.update(
            status="SESSION_ERROR", errors=[prompt_texts.text("feedback.message_conflict")]
        )
        return None
    if "response" not in entry:
        return prompt_texts.text("feedback.dispatch_interrupted")
    outcome.update(entry["outcome"])
    return entry["response"]
