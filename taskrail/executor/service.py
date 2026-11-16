"""Linux peer-authenticated socket with root-only approval."""

import argparse
import os
import socket
import socketserver
from pathlib import Path

from taskrail.executor import (
    inventory,
    jenkins_config,
    jenkins_schema,
    protocol,
    socket_io,
    tickets,
    worker,
)
from taskrail.executor.hosts import load as load_hosts
from taskrail.executor.hosts import public as public_hosts
from taskrail.executor.store import TicketStore

PRIVATE_UMASK = 0o77
IDENTIFIER = "id"
DIGEST = "digest"
PRIVILEGED = frozenset(("approve", "reject"))
ERROR_FIELD = "error"
INVALID_REQUEST = (ValueError, OSError, LookupError, TypeError)
# Maintenance excludes all operations that can start remote work.
HELD = frozenset(("submit", "run-ssh", "approve"))


class ExecutorServer(socketserver.ThreadingUnixStreamServer):
    """Authenticate the application UID for SSH and reserve privileged decisions for Jenkins."""

    daemon_threads = True
    maintenance = Path(protocol.MAINTENANCE_MARKER)

    def __init__(self, address, uid, inventory, store, jenkins=None):
        self.client_uid = uid
        self.configs = {tickets.SSH: inventory, tickets.JENKINS: jenkins or {}}
        self.store = store
        super().__init__(address, None, bind_and_activate=not isinstance(address, socket.socket))
        if isinstance(address, socket.socket):
            self.socket.close()
            self.socket = address

    def dispatch(self, payload, uid, descriptor=None):
        """Keep the approval route inaccessible to the application UID."""
        if uid not in (0, self.client_uid):
            raise ValueError("Unauthorized local account")
        operation = payload.get("operation")
        if operation in HELD and self.maintenance.exists():
            raise protocol.MaintenanceError(
                "Executor maintenance is in progress; nothing was submitted or approved. Try again after it ends."
            )
        if operation in PRIVILEGED and uid == 0:
            return self.decide(operation, payload)
        if operation == "catalog":
            return catalog(self.configs, payload, descriptor)
        if operation in {"run-ssh", "submit"}:
            return self.submit(payload, descriptor)
        if operation == "status":
            return self.store.get(payload[IDENTIFIER])
        if operation == "jenkins-read":
            return self.jenkins_read(payload["request"])
        raise ValueError("Unsupported operation or privileged approval required")

    def run_ssh(self, payload, descriptor):
        """Reserve the immutable request before connecting, including after lost replies."""
        if tickets.submission_kind(payload) != tickets.SSH:
            raise ValueError("Expected an SSH action")
        identifier = protocol.fingerprint(payload)
        with self.store.lock:
            try:
                return self.store.get(identifier)
            except FileNotFoundError:
                config = target_config(self.configs, payload, descriptor)
            ticket = self.store.save(tickets.ssh_ticket(payload, config, identifier))
        return worker.launch(self.store, ticket, config)

    def submit(self, payload, descriptor):
        """Only Jenkins jobs use the configured approval policy."""
        if payload["operation"] == "run-ssh":
            return self.run_ssh(payload, descriptor)
        kind = tickets.submission_kind(payload)
        if kind != tickets.JENKINS or inventory.KEY in payload:
            raise ValueError("Use run-ssh for SSH actions")
        ticket = self.store.submit(payload, self.configs[kind])
        if ticket["status"] == "PENDING_APPROVAL" and tickets.preapproved(
            self.configs[kind], ticket["action"]
        ):
            return self.decide("approve", {IDENTIFIER: ticket[IDENTIFIER], DIGEST: ticket[DIGEST]})
        return ticket

    def decide(self, operation, payload):
        """Root rejects, or approves and starts exactly one execution.

        A build that root allowed in advance in the Jenkins configuration is approved
        here on submission, against the same digest and identity checks.
        """
        identifier = payload[IDENTIFIER]
        saved = self.store.get(identifier)
        if tickets.stored_kind(saved) != tickets.JENKINS:
            raise ValueError("Only Jenkins builds accept approval decisions")
        if operation == "reject":
            return self.store.reject(identifier, payload[DIGEST])
        config = self.configs[tickets.JENKINS]
        ticket = self.store.approve(identifier, payload[DIGEST], config)
        return worker.launch(self.store, ticket, config)

    def jenkins_read(self, request):
        """Reads were approved in the application; builds always go through a ticket."""
        servers = self.configs[tickets.JENKINS]
        jenkins_schema.validate(request, servers)
        if request["operation"] not in jenkins_schema.READS:
            raise ValueError("Jenkins builds require a root-approved ticket")
        from taskrail.executor import jenkins_reads

        return jenkins_reads.read(servers, request)

    def finish_request(self, request, client_address):
        """Serve one authenticated request without retaining a client session."""
        request.settimeout(10)
        uid = socket_io.peer(request)
        if uid not in (0, self.client_uid):
            request.sendall(protocol.encode({ERROR_FIELD: "Unauthorized local account"}))
            return
        try:
            with socket_io.received(request) as (payload, descriptor):
                response = self.dispatch(payload, uid, descriptor)
        except protocol.MaintenanceError as error:
            response = {ERROR_FIELD: str(error), protocol.MAINTENANCE: True}
        except inventory.InventoryError as error:
            response = {ERROR_FIELD: str(error), "inventory_error": True}
        except INVALID_REQUEST:
            response = {
                ERROR_FIELD: "Executor rejected request; check fields, targets and permissions"
            }
        request.sendall(protocol.encode(response))


def target_config(configs, payload, descriptor):
    if inventory.KEY not in payload:
        return configs[tickets.SSH]
    return inventory.load(payload[inventory.KEY], descriptor)


def catalog(configs, payload, descriptor=None):
    jenkins = jenkins_config.public(configs[tickets.JENKINS])
    target_hosts = target_config(configs, payload, descriptor)
    shown = dict(hosts=public_hosts(target_hosts), jenkins=jenkins)
    shown["inventory_lookup"] = True
    shown["ssh_execution"] = "automatic"
    shown["inventory_files"] = inventory.published()
    if inventory.KEY in payload:
        shown[inventory.KEY] = payload.get(inventory.KEY)
    return shown


def main():
    """Run the root-installed service as its dedicated system user."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-uid", type=int, required=True)
    args = parser.parse_args()
    if args.client_uid <= 0:
        parser.error("The application account must not be root")
    os.umask(PRIVATE_UMASK)
    serve(args.client_uid)


def serve(client_uid):
    """Recover tickets, load the configuration and answer on the private socket."""
    store = TicketStore()
    store.recover()
    inventory = load_hosts()
    jenkins = jenkins_config.load()
    with (
        socket_io.listener() as listener,
        ExecutorServer(listener, client_uid, inventory, store, jenkins) as server,
    ):
        server.serve_forever()


if __name__ == "__main__":
    main()
