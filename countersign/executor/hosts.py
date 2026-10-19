"""Private server credentials never enter an orchestrator request."""

import json
import re
from pathlib import Path

from countersign.core.schema import require
from countersign.executor import protocol

IDENTITY = "identity_file"
PASSWORD = "password"
CONNECTION_FIELDS = frozenset(("hostname", "port", "username"))
# Exactly one authentication field per host; key files stay in the executor's root-owned config.
AUTH_FIELDS = (PASSWORD, IDENTITY)
KEY_DIRECTORY = "/etc/countersign-executor/"
MAX_PORT = 65535
PORT = "port"

CONFIG = Path("/etc/countersign-executor/hosts.json")


def load(path=CONFIG):
    """Validate the root-managed target inventory."""
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(inventory, dict):
        raise ValueError("The host inventory must be an object; use {} for none")
    for alias, host in inventory.items():
        protocol.label(alias)
        validate(host)
    return inventory


def validate(host):
    """Keep all SSH option and destination fields server-owned."""
    if not isinstance(host, dict) or set(host) not in [
        CONNECTION_FIELDS | {auth} for auth in AUTH_FIELDS
    ]:
        raise ValueError(
            "Each host requires hostname, port, username and password or identity_file"
        )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", host["hostname"]):
        raise ValueError("Invalid hostname")
    protocol.label(host["username"])
    port = host[PORT]
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValueError("SSH port must be an integer")
    require(1 <= port <= MAX_PORT, "Invalid SSH port")
    password = host.get(PASSWORD)
    if password is None:
        validate_identity(host[IDENTITY])
    else:
        protocol.text(password)


def validate_identity(path):
    """A private key path is absolute, normalized and inside the executor configuration."""
    require(isinstance(path, str) and Path(path).is_absolute(), "identity_file must be absolute")
    candidate = Path(path)
    require(str(candidate) == path and ".." not in candidate.parts, "Invalid identity_file")
    require(path.startswith(KEY_DIRECTORY), f"identity_file must be under {KEY_DIRECTORY}")


def public(inventory):
    """Expose aliases and connection identity, excluding secrets."""
    return {
        alias: {key: host[key] for key in ("hostname", "port", "username")}
        for alias, host in inventory.items()
    }


def redact(output, inventory):
    """Remove configured passwords from captured server output."""
    passwords = [host.get(PASSWORD) for host in inventory.values()]
    for password in filter(None, passwords):
        output = output.replace(password, "[REDACTED]")
    return output
