"""Keep isolated SSH actions in the same stage without weakening root approval.

The server decides what an action may do (see execution_requests.remote_mode): before
the operator confirms a change it only inspects, whatever the model writes.
"""

from countersign.application import execution_requests, execution_wait
from countersign.core import prompt_texts
from countersign.interactions import remote_inspection
from countersign.interactions.clock import ApprovalPause


def consume(session, text):
    """Remote tickets retain their separate timeout and privileged approval authority."""
    action = execution_requests.extract(text)
    if action is None:
        return None
    run = session.environment["run"]
    config = session.environment.get("config", {})
    mode = execution_requests.remote_mode(run, config, session.active[1]["role"])
    if mode is None:
        return prompt_texts.text("feedback.ssh_refused")
    if mode == execution_requests.INSPECT:
        try:
            action = remote_inspection.inspection(action)
        except ValueError as error:
            return prompt_texts.text(
                "feedback.inspection_refused", error=error, commands=remote_inspection.listed()
            )
    execution_wait.submit(run, session.active[0], action)
    with ApprovalPause(session):
        return execution_wait.resume(run, session.state)
