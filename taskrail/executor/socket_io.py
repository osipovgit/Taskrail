"""An optional read-only descriptor accompanies the first byte of a local request."""

import os
import socket
import struct
from contextlib import ExitStack, contextmanager

from taskrail.core.schema import require
from taskrail.executor import inventory_file, protocol

PEER_CREDENTIAL_BYTES = 12
SYSTEMD_FD = 3
DESCRIPTOR = struct.Struct("i")


def listener():
    owner = os.environ.get("LISTEN_PID") == str(os.getpid())
    if not owner or os.environ.get("LISTEN_FDS") != "1":
        raise ValueError("Start the executor through taskrail-executor.socket")
    os.set_inheritable(SYSTEMD_FD, False)
    return socket.socket(fileno=SYSTEMD_FD)


def peer(connection):
    credentials = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, PEER_CREDENTIAL_BYTES
    )
    return struct.unpack("3i", credentials)[1]


def send(connection, payload):
    """Send the descriptor on the first byte, followed by the ordinary request frame."""
    wire = protocol.encode(payload)
    selection = payload.get("ssh_inventory")
    if not inventory_file.project(selection):
        connection.sendall(wire)
        return
    try:
        stream = inventory_file.opened(selection[inventory_file.FILENAME])
    except (OSError, ValueError):
        # The broker can still return a previously submitted ticket or a typed refusal.
        connection.sendall(wire)
        return
    with stream:
        socket.send_fds(connection, [wire[:1]], [stream.fileno()])
    connection.sendall(wire[1:])


@contextmanager
def received(connection):
    """Close all received rights, including on invalid or truncated messages."""
    frame = connection.recvmsg(1, socket.CMSG_LEN(DESCRIPTOR.size), socket.MSG_CMSG_CLOEXEC)
    with ExitStack() as stack:
        fds = descriptors(frame[1], stack)
        require(frame[0], "Empty executor frame")
        require(not frame[2] & socket.MSG_CTRUNC, "Incomplete executor frame")
        require(len(fds) <= 1, "Expected at most one descriptor")
        with connection.makefile("rb") as stream:
            payload = protocol.receive(stream, frame[0])
            yield payload, next(iter(fds), None)


def descriptors(ancillary, stack):
    received_fds = []
    for level, kind, raw in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            for entry in DESCRIPTOR.iter_unpack(raw):
                stack.callback(os.close, entry[0])
                received_fds.append(entry[0])
    return received_fds
