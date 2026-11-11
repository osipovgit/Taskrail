"""Run the one executor request of a response, or tell the session what to fix."""

from types import MappingProxyType

from taskrail.core import prompt_texts, task_understanding
from taskrail.git.deadline import Deadline
from taskrail.interactions import (
    events,
    executor_delivery,
    jenkins,
    local_route,
    remote,
    request_envelope,
    request_limits,
    turn_recovery,
)

RESPONSE = "final_text"


def route(actions, outcome):
    """The response to a request, or None when the response is not one."""
    text = outcome[RESPONSE]
    kind = request_envelope.status(text)
    if kind is None:
        return None
    if actions.session.active[1]["stage"] == task_understanding.STAGE:
        return feedback(actions, outcome, kind)
    try:
        payload = request_envelope.parsed(kind, text)
    except ValueError as error:
        message = prompt_texts.text("feedback.rejected_request", status=kind, error=error)
        return feedback(actions, outcome, kind, message)
    return executor_delivery.route(actions, outcome, kind, payload, dispatch)


def dispatch(actions, outcome, kind, payload):
    """Only a new model operation consumes a request count or reaches its executor."""
    if kind in {request_envelope.LOCAL, request_envelope.GIT} and request_limits.check(
        actions.session, outcome, payload
    ):
        return None
    return ROUTES[kind](actions, payload)


def run_git(actions, payload):
    """Show Git execution immediately and share the stage deadline across probes."""
    event = events.begin(actions.folder, "git", payload)
    try:
        response = git_response(actions, payload)
    except BaseException:
        events.finish(
            actions.folder, event, "Interrupted; inspect the Git action journal before retrying."
        )
        raise
    events.finish(actions.folder, event, response)
    return response


def git_response(actions, payload):
    """A push waits for the operator first, outside the deadline, like every approval."""
    refused = actions.push_refusal(payload)
    if refused:
        return refused
    with Deadline(actions.session.clock.remaining(), actions.run):
        return actions.git_action(payload)


def run_remote(actions, payload):
    """An SSH action keeps its own root approval route."""
    return remote.consume(actions.session, payload)


def feedback(actions, outcome, kind, message=None):
    """Return an available next action; stop only when unchanged feedback stalls."""
    if actions.session.active[1]["stage"] == task_understanding.STAGE:
        message = prompt_texts.text("understanding.executor")
    if turn_recovery.repeated_feedback(actions.session, kind, message):
        outcome.update(status="INVALID_RESULT", contract_error=message)
        return None
    events.correction(actions.session, "request", outcome[RESPONSE], message)
    return message


ROUTES = MappingProxyType(
    {
        request_envelope.GIT: run_git,
        request_envelope.LOCAL: local_route.run_local,
        request_envelope.ACTION: run_remote,
        request_envelope.JENKINS: jenkins.consume,
    }
)
