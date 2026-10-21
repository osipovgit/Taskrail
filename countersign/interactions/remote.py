"""Keep isolated SSH actions in the same stage without weakening root approval.

The server decides what an action may do (see execution_requests.remote_mode): before
the operator confirms a change it only inspects, whatever the model writes.
"""

from countersign.application import execution_requests, execution_wait
from countersign.interactions import remote_inspection
from countersign.interactions.clock import ApprovalPause

REFUSED = "Server actions are not available while implementing; checks on servers run after the operator confirms the changes. Nothing was executed. Continue without it."
INSPECTION_REFUSED = "Nothing was executed: {0}. Before the operator confirms the changes, an SSH action runs exactly one read-only command and no files: {1}. Arguments are passed literally, so pipes, redirects, globs and variables do not work. A check that changes a server belongs in a 'Server check:' entry of unverified."


def consume(session, text):
    """Remote tickets retain their separate timeout and privileged approval authority."""
    action = execution_requests.extract(text)
    if action is None:
        return None
    run = session.environment["run"]
    config = session.environment.get("config", {})
    mode = execution_requests.remote_mode(run, config, session.active[1]["role"])
    if mode is None:
        return REFUSED
    if mode == execution_requests.INSPECT:
        try:
            action = remote_inspection.inspection(action)
        except ValueError as error:
            return INSPECTION_REFUSED.format(error, remote_inspection.listed())
    execution_wait.submit(run, session.active[0], action)
    with ApprovalPause(session):
        return execution_wait.resume(run, session.state)
