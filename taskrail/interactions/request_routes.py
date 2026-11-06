"""Run the one executor request of a response, or tell the session what to fix."""

from types import MappingProxyType

from taskrail.core import prompt_texts
from taskrail.git.deadline import Deadline
from taskrail.interactions import (
    events,
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
    try:
        payload = request_envelope.parsed(kind, text)
    except ValueError as error:
        return rejected_request(actions, outcome, kind, error)
    if kind in {request_envelope.LOCAL, request_envelope.GIT} and request_limits.check(
        actions.session, outcome, payload
    ):
        return None
    return ROUTES[kind](actions, outcome, payload)


def run_git(actions, outcome, payload):
    """Show Git execution immediately and share the stage deadline across probes."""
    event = events.begin(actions.folder, "git", payload)
    try:
        response = git_response(actions, outcome, payload)
    except BaseException:
        events.finish(
            actions.folder, event, "Interrupted; inspect the Git action journal before retrying."
        )
        raise
    events.finish(actions.folder, event, response)
    return response


def git_response(actions, outcome, payload):
    """A push waits for the operator first, outside the deadline, like every approval."""
    refused = actions.push_refusal(payload)
    if refused:
        return refused
    with Deadline(actions.session.clock.remaining(), actions.run):
        return actions.git_action(outcome)


def run_remote(actions, outcome, payload):
    """An SSH action keeps its own root approval route."""
    return remote.consume(actions.session, outcome[RESPONSE])


def run_jenkins(actions, outcome, payload):
    """A Jenkins read or build keeps its own approval route."""
    return jenkins.consume(actions, outcome[RESPONSE])


def rejected_request(actions, outcome, kind, error):
    """A request with a wrong shape runs nothing; the session may correct it in a row.

    After MAX_CORRECTIONS in a row the turn ends as an invalid result, like any other
    unusable response.
    """
    if turn_recovery.repeated_feedback(actions.session, kind, str(error)):
        outcome.update(status="INVALID_RESULT", contract_error=f"{kind} rejected: {error}")
        return None
    feedback = prompt_texts.text("feedback.rejected_request", status=kind, error=error)
    events.correction(actions.session, "request", outcome[RESPONSE], feedback)
    return feedback


ROUTES = MappingProxyType(
    {
        request_envelope.GIT: run_git,
        request_envelope.LOCAL: local_route.run_local,
        request_envelope.ACTION: run_remote,
        request_envelope.JENKINS: run_jenkins,
    }
)
