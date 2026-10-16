"""Private server credentials never enter an orchestrator request."""

import json
import re
from pathlib import Path

from countersign.core.schema import require
from countersign.executor import protocol

HOST_FIELDS = frozenset(("hostname", "port", "username", "password"))
MAX_PORT = 65535
PORT = "port"

CONFIG = Path("/etc/countersign-executor/hosts.json")


def load(path=CONFIG):
    """Validate the root-managed target inventory."""
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("Configure at least one executor host")
    for alias, host in inventory.items():
        protocol.label(alias)
        validate(host)
    return inventory


def validate(host):
    """Keep all SSH option and destination fields server-owned."""
    if not isinstance(host, dict) or set(host) != HOST_FIELDS:
        raise ValueError("Each host requires hostname, port, username and password")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", host["hostname"]):
        raise ValueError("Invalid hostname")
    protocol.label(host["username"])
    port = host[PORT]
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValueError("SSH port must be an integer")
    require(1 <= port <= MAX_PORT, "Invalid SSH port")
    protocol.text(host["password"])


def public(inventory):
    """Expose aliases and connection identity, excluding secrets."""
    return {
        alias: {key: host[key] for key in ("hostname", "port", "username")}
        for alias, host in inventory.items()
    }


def redact(output, inventory):
    """Remove configured passwords from captured server output."""
    for host in inventory.values():
        output = output.replace(host["password"], "[REDACTED]")
    return output
