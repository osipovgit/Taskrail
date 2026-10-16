"""Keep isolated SSH actions in the same stage without weakening root approval."""

from countersign.application import execution_requests, execution_wait
from countersign.interactions.clock import ApprovalPause


def consume(session, text):
    """Remote tickets retain their separate timeout and privileged approval authority."""
    action = execution_requests.extract(text)
    if action is None:
        return None
    run = session.environment["run"]
    execution_wait.submit(run, session.active[0], action)
    with ApprovalPause(session):
        return execution_wait.resume(run, session.state)
