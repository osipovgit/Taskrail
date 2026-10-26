"""Executor-owned durable tickets with single-use approval."""

import json
import os
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from taskrail.core.files import atomic_json
from taskrail.executor import protocol, tickets

PRIVATE_DIRECTORY_MODE = 0o700

STATE = Path("/var/lib/taskrail-executor")


class TicketStore:
    """Serialize submissions and approval before any remote side effect."""

    def __init__(self, directory=STATE):
        self.directory = directory
        self.lock = threading.RLock()
        directory.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)

    def save(self, ticket):
        """Persist the ticket and its directory entry before launching SSH."""
        atomic_json(self.directory / "{id}.json".format(**ticket), ticket)
        with closing(DirectoryHandle(self.directory)) as descriptor:
            os.fsync(descriptor.number)
        return ticket

    def get(self, identifier):
        """Identifiers cannot escape the private spool."""
        return json.loads(
            (self.directory / f"{protocol.label(identifier)}.json").read_text(encoding="utf-8")
        )

    def submit(self, payload, inventory):
        """The client key makes transport retries idempotent, not re-executions."""
        protocol.label(payload["key"])
        kind, action, identity = tickets.described(payload, inventory)
        ticket = dict(
            id=protocol.fingerprint(payload),
            kind=kind,
            action=action,
            targets=identity,
            status="PENDING_APPROVAL",
            created_at=datetime.now(timezone.utc).isoformat(),
            results=[],
        )
        ticket["digest"] = protocol.fingerprint(dict(action=action, targets=identity))
        with self.lock:
            if (self.directory / "{id}.json".format(**ticket)).exists():
                return self.get(ticket["id"])
            return self.save(ticket)

    def approve(self, identifier, digest, inventory):
        """Consume exactly the reviewed content, once, under the store lock."""
        with self.lock:
            ticket = self.get(identifier)
            if ticket["status"] != "PENDING_APPROVAL" or ticket["digest"] != digest:
                raise ValueError("Ticket changed or approval was already consumed")
            if tickets.identity(ticket, inventory) != ticket["targets"]:
                raise ValueError("Target identity changed; submit and review a new ticket")
            ticket.update(status="RUNNING", approved_at=datetime.now(timezone.utc).isoformat())
            return self.save(ticket)

    def reject(self, identifier, digest):
        """Decline a pending ticket without executing any remote command."""
        with self.lock:
            ticket = self.get(identifier)
            if ticket["status"] != "PENDING_APPROVAL" or ticket["digest"] != digest:
                raise ValueError("Ticket changed or is no longer pending")
            ticket.update(status="REJECTED", detail="Operator rejected this exact action")
            return self.save(ticket)

    def recover(self):
        """Never replay an interrupted remote action after a daemon restart."""
        for path in self.directory.glob("*.json"):
            ticket = self.get(path.stem)
            if ticket["status"] == "RUNNING":
                ticket.update(
                    status="UNKNOWN",
                    detail="Executor restarted; inspect remote state before any new action",
                )
                self.save(ticket)


class DirectoryHandle:
    """Close a directory descriptor after durable ticket publication."""

    def __init__(self, path):
        self.number = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)

    def close(self):
        """Release the fsync descriptor."""
        os.close(self.number)
