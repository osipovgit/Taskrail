"""Sequential target execution without automatic retries."""

from datetime import datetime, timezone

from countersign.executor import hosts, transport

STATUS = "status"


def perform(store, ticket, inventory):
    """Stop after the first failed target and preserve previous outcomes."""
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
    ticket["finished_at"] = datetime.now(timezone.utc).isoformat()
    store.save(ticket)
