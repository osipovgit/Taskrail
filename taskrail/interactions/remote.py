"""Keep isolated SSH actions in the same stage without weakening root approval.

The server decides what an action may do (see execution_requests.remote_mode): before
the operator confirms a change it only inspects, whatever the model writes.
"""

from taskrail.application import execution_requests, execution_wait, remote_catalog
from taskrail.core import prompt_texts
from taskrail.executor import inventory, remote_inspection
from taskrail.interactions.clock import ApprovalPause


def consume(session, action):
    """Remote tickets retain their separate timeout and privileged approval authority."""
    run = session.environment["run"]
    config = session.environment.get("config", {})
    selection = session.state.get(inventory.KEY)
    mode = execution_requests.remote_mode(run, config, session.active[1]["role"])
    if mode is None:
        return prompt_texts.text("feedback.ssh_refused")
    if mode == execution_requests.INSPECT or selection:
        try:
            action = remote_inspection.inspection(action)
        except ValueError as error:
            return prompt_texts.text(
                "feedback.inspection_refused", error=error, commands=remote_inspection.listed()
            )
    return submit_to_targets(session, action, selection)


def submit_to_targets(session, action, selection):
    refused = target_refusal(action, remote_catalog.available(selection))
    if refused:
        return refused
    run = session.environment["run"]
    execution_wait.submit(run, session.active[0], execution_wait.ssh_request(action, selection))
    with ApprovalPause(session):
        return execution_wait.resume(run, session.state)


def target_refusal(action, catalog):
    """Do not start waiting on a ticket the configured route cannot accept."""
    if catalog.get(remote_catalog.UNAVAILABLE):
        return remote_catalog.unavailable(catalog)
    targets = catalog.get("hosts", {})
    if not targets:
        return prompt_texts.text("routes.ssh.empty")
    missing = [name for name in action["targets"] if name not in targets]
    if missing:
        return prompt_texts.text("feedback.ssh_targets", missing=", ".join(missing))
    return None
