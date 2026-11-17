"""Private server credentials never enter an orchestrator request."""

import json
import re
from pathlib import Path

from taskrail.core.schema import require
from taskrail.executor import protocol

CONNECTION_FIELDS = frozenset(("hostname", "port", "username"))
# Exactly one authentication field per host; key files stay in the executor's root-owned config.
AUTH_FIELDS = ("password", "identity_file")
PASSWORD, IDENTITY = AUTH_FIELDS
KEY_DIRECTORY = "/etc/taskrail-executor/"
MAX_PORT = 65535
PORT = "port"

CONFIG = Path("/etc/taskrail-executor/hosts.json")


class InvalidConnection(ValueError):
    """A field diagnostic safe to report without exposing private host settings."""


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
    validate_address(host)
    if PASSWORD in host:
        try:
            protocol.text(host.get(PASSWORD))
        except ValueError:
            raise InvalidConnection("Expected a valid, nonempty SSH password string.") from None
    else:
        validate_identity(host[IDENTITY])


def validate_address(host):
    hostname = host["hostname"]
    if not isinstance(hostname, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", hostname):
        raise InvalidConnection("Invalid SSH hostname or address.")
    try:
        protocol.label(host["username"])
    except ValueError:
        raise InvalidConnection("Invalid SSH username.") from None
    port = host[PORT]
    integer = isinstance(port, int) and not isinstance(port, bool)
    if not integer or not 1 <= port <= MAX_PORT:
        raise InvalidConnection("SSH port must be an integer between 1 and 65535.")


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
    passwords = {host.get(PASSWORD) for host in inventory.values()}
    for password in sorted(filter(None, passwords), key=len, reverse=True):
        output = output.replace(password, "[REDACTED]")
    return output
