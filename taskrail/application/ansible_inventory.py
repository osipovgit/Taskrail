"""Resolve an inventory in the trusted project environment, outside the SSH executor."""

import json
import os
import subprocess
from pathlib import Path

from taskrail.application import ansible_defaults
from taskrail.executor import inventory_connection

INVALID_HOST_DATA = (AttributeError, KeyError, TypeError, ValueError)


def resolve(selection):
    source = Path(selection["file"])
    group = selection["group"]
    listing = command(["ansible-inventory", "-i", str(source), "--list"], source)
    if not isinstance(listing, dict) or group == "_meta" or group not in listing:
        raise inventory_connection.InventoryError(
            "The selected group is absent from the resolved inventory."
        )
    defaults = ansible_defaults.configured(command, source)
    try:
        return selected_hosts(listing, group, defaults)
    except INVALID_HOST_DATA:
        raise inventory_connection.InventoryError(
            "Invalid host data in the resolved Ansible inventory."
        ) from None


def command(argv, source):
    """Keep all raw output, including parser errors containing credentials, private."""
    environment = dict(
        os.environ,
        ANSIBLE_INVENTORY=str(source),
        ANSIBLE_NOCOLOR="1",
        ANSIBLE_LOG_PATH=os.devnull,
        ANSIBLE_INVENTORY_UNPARSED_IS_FAILED="true",
    )
    try:
        outcome = subprocess.run(
            argv,
            cwd=source if source.is_dir() else source.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except OSError:
        raise inventory_connection.InventoryError(
            f"Cannot start {argv[0]} in the project environment."
        ) from None
    if outcome.returncode:
        raise inventory_connection.InventoryError(
            f"{argv[0]} exited with code {outcome.returncode}. Check the source, project configuration, "
            "installed plugins and credentials in the controller environment."
        )
    try:
        return json.loads(outcome.stdout)
    except (ValueError, RecursionError):
        raise inventory_connection.InventoryError(f"{argv[0]} did not return JSON.") from None


def selected_hosts(listing, group, defaults):
    # Ansible host patterns can match a host with the same name as a different group.
    # Use the exact resolved group and include members missing from _meta.hostvars.
    variables = listing["_meta"]["hostvars"]
    return {
        alias: ansible_defaults.host_settings(variables.get(alias, {}), defaults)
        for alias in members(listing, group)
    }


def members(listing, group):
    pending = [group]
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        body = listing.get(name, {})
        yield from body.get("hosts", [])
        pending.extend(reversed(body.get("children", [])))


def binding_request(selection):
    return {"operation": "bind-inventory", "ssh_inventory": selection, "hosts": resolve(selection)}
