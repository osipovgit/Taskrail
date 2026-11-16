"""Authorize a pinned project inventory and start it when the ordinary user supplies it."""

from datetime import datetime, timezone

from taskrail.executor import inventory, inventory_file, worker


def authorize(store, identifier, digest):
    """Record root consent; the application supplies the pinned file before execution."""
    with store.lock:
        ticket = store.get(identifier)
        if ticket["status"] != "PENDING_APPROVAL" or ticket["digest"] != digest:
            raise ValueError("Ticket changed or approval was already consumed")
        ticket.update(status="APPROVED", approved_at=datetime.now(timezone.utc).isoformat())
        return store.save(ticket)


def start(store, payload, descriptor):
    """Only a previously authorized ticket can consume the supplied project inventory."""
    with store.lock:
        saved = store.get(payload["id"])
        selected = saved.get(inventory.KEY)
        if not inventory_file.project(selected) or payload.get(inventory.KEY) != selected:
            raise ValueError("Inventory selection differs from the reviewed ticket")
        if saved["status"] != "APPROVED":
            return saved
        try:
            config = inventory.load(selected, descriptor)
        except inventory.InventoryError as error:
            saved.update(status="REJECTED", inventory_error=str(error))
            return store.save(saved)
        ticket = store.approve(saved["id"], saved["digest"], config, expected="APPROVED")
    return worker.launch(store, ticket, config)
