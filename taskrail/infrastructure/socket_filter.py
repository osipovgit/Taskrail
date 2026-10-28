"""How a sandboxed command is cut off the network.

A private network namespace where the host allows one, else a seccomp program for
hosts that forbid configuring it: every socket but Unix and netlink ones is refused
with EACCES. Calls of another architecture, x32 calls and io_uring, which could
bypass the socket check, are refused or killed.
"""

import contextlib
import errno
import platform
import struct
import tempfile
from types import MappingProxyType

NAMESPACE = "network namespace"
FILTER = "socket filter"

# struct sock_filter instructions and seccomp return values from the Linux UAPI.
LOAD = 0x20
JUMP_EQUAL = 0x15
JUMP_ABOVE_EQUAL = 0x35
RETURN = 0x6
ALLOW = 0x7FFF0000
KILL = 0x80000000
ERRNO_ACTION = 0x50000
REFUSE = ERRNO_ACTION | errno.EACCES
# Offsets of the architecture, the call number and its first argument in seccomp_data.
ARCHITECTURE_FIELD = 4
CALL_FIELD = 0
FIRST_ARGUMENT = 16
# Audit architecture and socket call number per machine.
MACHINES = MappingProxyType({"x86_64": (0xC000003E, 41), "aarch64": (0xC00000B7, 198)})
X32_CALLS = 0x40000000
IO_URING_SETUP = 425
LOCAL_SOCKETS = 1
NETLINK = 16


def program():
    """The compiled filter for this machine, or None when its calls are unknown."""
    known = MACHINES.get(platform.machine())
    if known is None:
        return None
    architecture, socket = known
    instructions = (
        (LOAD, 0, 0, ARCHITECTURE_FIELD),
        (JUMP_EQUAL, 1, 0, architecture),
        (RETURN, 0, 0, KILL),
        (LOAD, 0, 0, CALL_FIELD),
        (JUMP_ABOVE_EQUAL, 6, 0, X32_CALLS),
        (JUMP_EQUAL, 5, 0, IO_URING_SETUP),
        (JUMP_EQUAL, 0, 3, socket),
        (LOAD, 0, 0, FIRST_ARGUMENT),
        (JUMP_EQUAL, 1, 0, LOCAL_SOCKETS),
        (JUMP_EQUAL, 0, 1, NETLINK),
        (RETURN, 0, 0, ALLOW),
        (RETURN, 0, 0, REFUSE),
    )
    return b"".join(struct.pack("=HBBI", *instruction) for instruction in instructions)


@contextlib.contextmanager
def isolation(kind):
    """bubblewrap options of this kind; the seccomp program is read from an inherited file."""
    if kind == NAMESPACE:
        yield dict(args=["--unshare-net"], pass_fds=())
        return
    with tempfile.TemporaryFile() as compiled:
        compiled.write(program())
        compiled.flush()
        compiled.seek(0)
        descriptor = compiled.fileno()
        yield dict(args=["--seccomp", str(descriptor)], pass_fds=(descriptor,))
