"""Keep a resolved project's SSH credentials in executor memory, separate from tickets."""

import hmac
import secrets

from taskrail.executor import inventory, inventory_connection, protocol


class Bindings:
    def __init__(self):
        self.selections = {}
        self.secret = secrets.token_bytes()

    def register(self, selection, rows, descriptor):
        key = self.key(selection, descriptor)
        connections = resolved_hosts(rows)
        signed = protocol.encode([selection, connections])
        token = hmac.digest(self.secret, signed, "sha256").hex()
        self.selections[key] = dict(selection, binding=token), connections
        return self.selections[key]

    def get(self, selection, descriptor):
        key = self.key(selection, descriptor)
        binding = self.selections.get(key)
        if binding is None or selection != binding[0]:
            raise inventory.InventoryError(
                "The SSH inventory binding expired or changed. Repeat the lookup."
            )
        return binding[1]

    def key(self, selection, descriptor):
        checked = inventory.checked(selection)
        inventory.verify_project(selection, descriptor)
        return checked["file"], checked["group"]


def checked_host(alias, settings, position):
    try:
        protocol.label(alias)
    except ValueError:
        raise inventory.InventoryError(
            f"Selected host #{position}: invalid SSH host alias."
        ) from None
    if not isinstance(settings, dict):
        raise inventory.InventoryError("Expected resolved SSH host variables.")
    try:
        return inventory_connection.bind(alias, settings)
    except inventory.InventoryError as error:
        raise inventory.InventoryError(f"Selected host #{position}: {error}") from None


def resolved_hosts(rows):
    if not isinstance(rows, dict) or not rows:
        raise inventory.InventoryError("The selected SSH inventory group contains no hosts.")
    return {
        alias: checked_host(alias, settings, position)
        for position, (alias, settings) in enumerate(rows.items(), 1)
    }
