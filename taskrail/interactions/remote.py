"""Run task-scoped SSH requests and deliver their observed outcomes to the same agent."""

from taskrail.application import execution_requests, execution_wait, remote_catalog
from taskrail.core import prompt_texts
from taskrail.executor import inventory


def consume(session, action):
    selection = session.state.get(inventory.KEY)
    refused = target_refusal(action, remote_catalog.available(selection))
    if refused:
        return refused
    run = session.environment["run"]
    execution_requests.verify_delivery(run, session.environment["config"])
    execution_wait.submit(run, session.active[0], execution_wait.ssh_request(action, selection))
    return execution_wait.resume(run, session.state)


def target_refusal(action, catalog):
    """Do not start waiting on a ticket the configured route cannot accept."""
    if catalog.get(remote_catalog.UNAVAILABLE):
        return remote_catalog.unavailable(catalog)
    targets = catalog.get("hosts", {})
    if not targets:
        return prompt_texts.text("routes.ssh.empty")
    if action["targets"] == "all":
        return None
    missing = [name for name in action["targets"] if name not in targets]
    if missing:
        return prompt_texts.text("feedback.ssh_targets", missing=", ".join(missing))
    return None
