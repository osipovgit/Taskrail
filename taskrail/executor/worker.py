"""Sequential target execution without automatic retries."""

from datetime import datetime, timezone

from taskrail.executor import hosts, jenkins_build, tickets, transport

STATUS = "status"


def perform(store, ticket, inventory):
    """Stop after the first failed target and preserve previous outcomes."""
    if tickets.kind_of(ticket) == tickets.JENKINS:
        outcome = jenkins_build.perform(inventory, ticket["action"])
        ticket["results"].append(outcome)
        ticket[STATUS] = outcome[STATUS]
        return finish(store, ticket)
    try:
        for alias in ticket["action"]["targets"]:
            outcome = transport.execute(inventory[alias], ticket["action"])
            outcome["output"] = hosts.redact(outcome["output"], inventory)
            ticket["results"].append(dict(target=alias, **outcome))
            store.save(ticket)
            if outcome[STATUS] != "SUCCEEDED":
                ticket[STATUS] = outcome[STATUS]
                break
        else:
            ticket[STATUS] = "SUCCEEDED"
    except (OSError, ValueError):
        ticket.update(
            status="UNKNOWN", detail="Transport failed; inspect remote state before retrying"
        )
    return finish(store, ticket)


def finish(store, ticket):
    """Record the end time and the final ticket."""
    ticket["finished_at"] = datetime.now(timezone.utc).isoformat()
    return store.save(ticket)
