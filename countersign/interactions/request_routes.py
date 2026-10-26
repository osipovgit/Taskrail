"""Run the one executor request of a response, or tell the session what to fix."""

from types import MappingProxyType

from countersign.core import prompt_texts
from countersign.git.deadline import Deadline
from countersign.interactions import events, jenkins, local_route, remote, request_envelope

MAX_CORRECTIONS = 2
CORRECTIONS = "corrections"
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
    """A request with a wrong shape runs nothing; the session may correct it twice.

    After that the turn ends as an invalid result, like any other unusable response.
    """
    context = actions.session.context
    if context[CORRECTIONS] >= MAX_CORRECTIONS:
        outcome.update(status="INVALID_RESULT", contract_error=f"{kind} rejected: {error}")
        return None
    context[CORRECTIONS] += 1
    feedback = prompt_texts.text("feedback.rejected_request", status=kind, error=error)
    events.append(actions.folder, "correction", dict(response=outcome[RESPONSE]), feedback)
    return feedback


ROUTES = MappingProxyType(
    {
        request_envelope.GIT: run_git,
        request_envelope.LOCAL: local_route.run_local,
        request_envelope.ACTION: run_remote,
        request_envelope.JENKINS: run_jenkins,
    }
)
