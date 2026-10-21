"""Linux peer-authenticated socket with root-only approval."""

import argparse
import grp
import os
import socket
import socketserver
import struct
import threading
from pathlib import Path

from countersign.executor import (
    hosts,
    jenkins_config,
    jenkins_reads,
    jenkins_schema,
    protocol,
    tickets,
    worker,
)
from countersign.executor.store import TicketStore

PEER_CREDENTIAL_BYTES = 12
PRIVATE_UMASK = 0o77
SOCKET_MODE = 0o660
IDENTIFIER = "id"
PRIVILEGED = frozenset(("approve", "reject"))
# Operations that could start remote work later; refused while maintenance runs.
HELD = frozenset(("submit", "approve"))


class ExecutorServer(socketserver.ThreadingUnixStreamServer):
    """The application account may submit; only root can authorize execution."""

    daemon_threads = True
    maintenance = Path(protocol.MAINTENANCE_MARKER)

    def __init__(self, address, uid, inventory, store, jenkins=None):
        self.client_uid = uid
        self.configs = {tickets.SSH: inventory, tickets.JENKINS: jenkins or {}}
        self.store = store
        super().__init__(address, None)

    def dispatch(self, payload, uid):
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
            jenkins = jenkins_config.public(self.configs[tickets.JENKINS])
            return dict(hosts=hosts.public(self.configs[tickets.SSH]), jenkins=jenkins)
        if operation == "submit":
            return self.store.submit(payload, self.configs[tickets.kind_of(payload)])
        if operation == "status":
            return self.store.get(payload[IDENTIFIER])
        if operation == "jenkins-read":
            return self.jenkins_read(payload["request"])
        raise ValueError("Unsupported operation or privileged approval required")

    def decide(self, operation, payload):
        """Root rejects, or approves and starts exactly one execution."""
        identifier = payload[IDENTIFIER]
        if operation == "reject":
            return self.store.reject(identifier, payload["digest"])
        config = self.configs[tickets.kind_of(self.store.get(identifier))]
        ticket = self.store.approve(identifier, payload["digest"], config)
        threading.Thread(
            target=worker.perform, args=(self.store, ticket, config), daemon=True
        ).start()
        return dict(id=ticket["id"], status="RUNNING")

    def jenkins_read(self, request):
        """Reads were approved in the application; builds always need a root ticket."""
        servers = self.configs[tickets.JENKINS]
        jenkins_schema.validate(request, servers)
        if request["operation"] not in jenkins_schema.READS:
            raise ValueError("Jenkins builds require a root-approved ticket")
        return jenkins_reads.read(servers, request)

    def finish_request(self, request, client_address):
        """Serve one authenticated request without retaining a client session."""
        request.settimeout(10)
        credentials = request.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, PEER_CREDENTIAL_BYTES
        )
        uid = struct.unpack("3i", credentials)[1]
        with request.makefile("rb") as stream:
            try:
                response = self.checked_dispatch(protocol.receive(stream), uid)
            except protocol.MaintenanceError as error:
                response = {"error": str(error), protocol.MAINTENANCE: True}
            except (ValueError, OSError, LookupError):
                response = {
                    "error": "Executor rejected request; check fields, targets and permissions"
                }
        request.sendall(protocol.encode(response))

    def checked_dispatch(self, payload, uid):
        """Translate malformed nested fields into protocol errors."""
        try:
            return self.dispatch(payload, uid)
        except TypeError as error:
            raise ValueError("Invalid executor field type") from error


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
    inventory = hosts.load()
    jenkins = jenkins_config.load()
    Path(protocol.SOCKET).unlink(missing_ok=True)
    with ExecutorServer(protocol.SOCKET, client_uid, inventory, store, jenkins) as server:
        os.chown(protocol.SOCKET, -1, grp.getgrnam("countersign-executor-clients").gr_gid)
        os.chmod(protocol.SOCKET, SOCKET_MODE)
        server.serve_forever()


if __name__ == "__main__":
    main()
