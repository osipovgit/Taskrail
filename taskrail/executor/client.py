"""Unprivileged clients can submit and observe, never grant approval."""

import socket

from taskrail.executor import protocol

CONNECTION_TIMEOUT = 15


def request(payload, address=protocol.SOCKET, timeout=CONNECTION_TIMEOUT):
    """Contact the local executor; the server checks the kernel peer UID."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(address)
        connection.sendall(protocol.encode(payload))
        with connection.makefile("rb") as stream:
            response = protocol.receive(stream)
    if response.get(protocol.MAINTENANCE):
        raise protocol.MaintenanceError(response.get("error"))
    if response.get("error"):
        raise ValueError(response.get("error"))
    return response
