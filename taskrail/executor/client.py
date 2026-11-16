"""Unprivileged clients can submit and observe, never grant approval."""

import socket

from taskrail.executor import inventory, protocol, socket_io

CONNECTION_TIMEOUT = 15


def request(payload, address=protocol.SOCKET, timeout=CONNECTION_TIMEOUT):
    """Contact the local executor; the server checks the kernel peer UID."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(address)
        socket_io.send(connection, payload)
        with connection.makefile("rb") as stream:
            response = protocol.receive(stream)
    message = response.get("error")
    if response.get(protocol.MAINTENANCE):
        raise protocol.MaintenanceError(message)
    if message and response.get("inventory_error"):
        raise inventory.InventoryError(message)
    if message:
        raise ValueError(message)
    return response
