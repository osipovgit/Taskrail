"""Executor-owned durable tickets for SSH requests and Jenkins builds."""

import json
import os
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from taskrail.core.files import atomic_json
from taskrail.executor import jenkins_config, protocol, tickets

PRIVATE_DIRECTORY_MODE = 0o700

STATUS = "status"
PENDING = "PENDING_APPROVAL"
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
        identifier = protocol.label(identifier)
        path = self.directory / f"{identifier}.json"
        ticket = json.loads(path.read_text(encoding="utf-8"))
        if ticket.get("kind") == tickets.SSH and ticket[STATUS] in {
            "SUCCEEDED",
            "FAILED",
            "UNKNOWN",
        }:
            parts = self.directory / identifier
            if parts.is_dir():
                records = {
                    int(part.stem): json.loads(part.read_text(encoding="utf-8"))
                    for part in parts.glob("*.json")
                }
                ticket["results"] = [records[index] for index in sorted(records)]
        return ticket

    def submit(self, payload, inventory):
        """Create a Jenkins ticket once, before its configured approval decision."""
        protocol.label(payload["key"])
        action = tickets.build_request(payload, inventory)
        identity = jenkins_config.identity(inventory, action)
        ticket = dict(
            id=protocol.fingerprint(payload),
            kind=tickets.JENKINS,
            action=action,
            targets=identity,
            digest=protocol.fingerprint(dict(action=action, targets=identity)),
            status=PENDING,
            created_at=datetime.now(timezone.utc).isoformat(),
            results=[],
        )
        with self.lock:
            try:
                return self.get(ticket["id"])
            except FileNotFoundError:
                return self.save(ticket)

    def approve(self, identifier, digest, inventory):
        """Consume exactly the reviewed content, once, under the store lock."""
        with self.lock:
            ticket = self.get(identifier)
            if ticket[STATUS] != PENDING or ticket["digest"] != digest:
                raise ValueError("Ticket changed or approval was already consumed")
            if jenkins_config.identity(inventory, ticket["action"]) != ticket["targets"]:
                raise ValueError("Target identity changed; submit and review a new ticket")
            ticket[STATUS] = "RUNNING"
            ticket.setdefault("approved_at", datetime.now(timezone.utc).isoformat())
            return self.save(ticket)

    def reject(self, identifier, digest):
        """Decline a pending ticket without executing any remote command."""
        with self.lock:
            ticket = self.get(identifier)
            if ticket[STATUS] != PENDING or ticket["digest"] != digest:
                raise ValueError("Ticket changed or already started")
            ticket.update(status="REJECTED", detail="Operator rejected this exact action")
            return self.save(ticket)

    def recover(self):
        """Never replay an interrupted remote action after a daemon restart."""
        for path in self.directory.glob("*.json"):
            ticket = json.loads(path.read_text(encoding="utf-8"))
            if ticket.get("kind") == tickets.SSH and ticket[STATUS] in {
                PENDING,
                "APPROVED",
            }:
                ticket.update(
                    status="REJECTED", detail="SSH execution policy changed; submit a new request"
                )
                self.save(ticket)
            elif ticket[STATUS] == "RUNNING":
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


def record_target(spool, identifier, index, outcome):
    """Persist a completed host without rewriting earlier outputs."""
    directory = spool / identifier
    directory.mkdir(mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
    atomic_json(directory / f"{index}.json", outcome)
    with closing(DirectoryHandle(directory)) as descriptor:
        os.fsync(descriptor.number)
