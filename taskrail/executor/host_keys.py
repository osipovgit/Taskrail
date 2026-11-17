"""Enroll a new SSH endpoint once, before offering credentials or starting its action."""

import os
import subprocess
import tempfile
from contextlib import closing, suppress
from pathlib import Path

from taskrail.core.files import digest
from taskrail.executor.inventory_connection import SSH_PORT
from taskrail.executor.store import PRIVATE_DIRECTORY_MODE, STATE, DirectoryHandle

PINNED = Path("/etc/taskrail-executor/known_hosts")
LEARNED = STATE / "host-keys"
CONNECT_TIMEOUT = 15


class HostKeyError(ValueError):
    """The executor could not prepare a trusted key file. No action was sent."""


def has_pin(address):
    outcome = subprocess.run(
        ["/usr/bin/ssh-keygen", "-F", address, "-f", str(PINNED)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if outcome.returncode == 1 and not outcome.stderr:
        return False
    if outcome.returncode:
        raise HostKeyError(f"Cannot check administrator SSH host keys in {PINNED}.")
    return True


def scan(hostname, port):
    # ssh-keyscan performs key exchange only. It has no password, identity file or action.
    outcome = subprocess.run(
        ["/usr/bin/ssh-keyscan", "-T", str(CONNECT_TIMEOUT), "-p", str(port), "--", hostname],
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    if outcome.returncode or not outcome.stdout.strip():
        raise HostKeyError(f"Could not obtain SSH host keys from {hostname} on port {port}.")
    return outcome.stdout


def trust_file(host):
    hostname, port = host["hostname"].lower(), host["port"]
    address = hostname if port == SSH_PORT else f"[{hostname}]:{port}"
    if has_pin(address):
        return Path(os.devnull)  # Only the administrator's global file applies to this endpoint.
    target = LEARNED / digest(address.encode("ascii"))
    if not target.exists():
        keys = scan(hostname, port)
        LEARNED.mkdir(mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
        publish(target, keys)
    return target


def publish(target, keys):
    """An overlapping first contact can use the winning keys but never replace them."""
    with tempfile.NamedTemporaryFile(dir=target.parent) as pending:
        pending.write(keys)
        pending.flush()
        os.fsync(pending.fileno())
        with suppress(FileExistsError):
            os.link(pending.name, target)
    # Enrollment can also create the host-keys directory on a fresh installation.
    for parent in (target.parent, target.parent.parent):
        with closing(DirectoryHandle(parent)) as directory:
            os.fsync(directory.number)
