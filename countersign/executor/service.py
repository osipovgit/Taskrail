"""Linux peer-authenticated socket with root-only approval."""

import argparse
import grp
import os
import socket
import socketserver
import struct
import threading
from pathlib import Path

from countersign.executor import hosts, protocol, worker
from countersign.executor.store import TicketStore

PEER_CREDENTIAL_BYTES = 12
PRIVATE_UMASK = 0o77
SOCKET_MODE = 0o660
IDENTIFIER = "id"


class ExecutorServer(socketserver.ThreadingUnixStreamServer):
    """The application account may submit; only root can authorize execution."""

    daemon_threads = True

    def __init__(self, address, uid, inventory, store):
        self.client_uid = uid
        self.inventory = inventory
        self.store = store
        super().__init__(address, None)

    def dispatch(self, payload, uid):
        """Keep the approval route inaccessible to the application UID."""
        if uid not in (0, self.client_uid):
            raise ValueError("Unauthorized local account")
        operation = payload.get("operation")
        if operation == "catalog":
            return dict(hosts=hosts.public(self.inventory))
        if operation == "submit":
            return self.store.submit(payload, self.inventory)
        if operation == "status":
            return self.store.get(payload[IDENTIFIER])
        if operation == "reject" and uid == 0:
            return self.store.reject(payload[IDENTIFIER], payload["digest"])
        if operation == "approve" and uid == 0:
            ticket = self.store.approve(payload[IDENTIFIER], payload["digest"], self.inventory)
            threading.Thread(
                target=worker.perform, args=(self.store, ticket, self.inventory), daemon=True
            ).start()
            return dict(id=ticket["id"], status="RUNNING")
        raise ValueError("Unsupported operation or privileged approval required")

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
    store = TicketStore()
    store.recover()
    Path(protocol.SOCKET).unlink(missing_ok=True)
    with ExecutorServer(protocol.SOCKET, args.client_uid, hosts.load(), store) as server:
        os.chown(protocol.SOCKET, -1, grp.getgrnam("countersign-executor-clients").gr_gid)
        os.chmod(protocol.SOCKET, SOCKET_MODE)
        server.serve_forever()


if __name__ == "__main__":
    main()
