"""Keep isolated SSH actions in the same stage without weakening root approval."""

from countersign.application import execution_requests, execution_wait
from countersign.interactions.clock import ApprovalPause

REFUSED = "Server actions are not available while implementing; checks on servers run after the operator confirms the changes. Nothing was executed. Continue without it."


def consume(session, text):
    """Remote tickets retain their separate timeout and privileged approval authority."""
    action = execution_requests.extract(text)
    if action is None:
        return None
    if session.active[1]["role"] == "implementer":
        return REFUSED
    run = session.environment["run"]
    execution_wait.submit(run, session.active[0], action)
    with ApprovalPause(session):
        return execution_wait.resume(run, session.state)
