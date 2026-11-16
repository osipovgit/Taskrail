"""Sequential target execution without automatic retries."""

import threading
from datetime import datetime, timezone

from taskrail.executor import hosts, jenkins_build, tickets, transport
from taskrail.executor.store import record_target

STATUS = "status"


def perform(store, ticket, inventory):
    """Record each target independently and never repeat an uncertain execution."""
    if tickets.stored_kind(ticket) == tickets.JENKINS:
        outcome = jenkins_build.perform(inventory, ticket["action"])
        ticket["results"].append(outcome)
        ticket[STATUS] = outcome[STATUS]
        return finish(store, ticket)
    status = "SUCCEEDED"
    for index, alias in enumerate(ticket["action"]["targets"]):
        outcome = run_target(inventory, alias, ticket["action"])
        outcome["target"] = alias
        record_target(store.directory, ticket["id"], index, outcome)
        if status != "UNKNOWN" and outcome[STATUS] != "SUCCEEDED":
            status = outcome[STATUS]
    ticket[STATUS] = status
    return finish(store, ticket)


def run_target(inventory, alias, action):
    try:
        outcome = transport.execute(inventory[alias], action)
    except (OSError, ValueError):
        return dict(
            status="UNKNOWN",
            exit_code=None,
            detail="Transport failed; inspect this host before retrying",
        )
    outcome["output"] = hosts.redact(outcome["output"], inventory)
    return outcome


def finish(store, ticket):
    """Record the end time and the final ticket."""
    ticket["finished_at"] = datetime.now(timezone.utc).isoformat()
    return store.save(ticket)


def launch(store, ticket, config):
    arguments = (store, ticket, config)
    try:
        threading.Thread(target=perform, args=arguments, daemon=True).start()
    except RuntimeError:
        ticket.update(status="FAILED", detail="Could not start executor worker")
        return finish(store, ticket)
    return dict(id=ticket["id"], status="RUNNING")
