"""Discover the selected executor targets without exposing authentication data."""

from taskrail.application import ansible_inventory, inventory_inputs, inventory_sources
from taskrail.core import prompt_texts
from taskrail.executor import client, inventory, inventory_file

UNAVAILABLE = "unavailable"
UPDATE = "routes.ssh.update"


def discover(selection):
    """Resolve once per explicit lookup. Other catalog reads use the frozen binding."""
    if not inventory_file.project(selection):
        return available(selection)
    readiness = available()
    if not readiness.get("native_inventory"):
        return readiness if UNAVAILABLE in readiness else {UNAVAILABLE: UPDATE}
    try:
        reply = client.request(ansible_inventory.binding_request(selection))
    except inventory.InventoryError as error:
        return {UNAVAILABLE: "routes.ssh.inventory_error", "detail": str(error)}
    except (OSError, ValueError) as error:
        return {UNAVAILABLE: reason(error)}
    return bound_catalog(reply, selection)


def bound_catalog(reply, selection):
    bound = reply.get(inventory.KEY, {})
    if not bound.get("binding") or selection != {
        key: entry for key, entry in bound.items() if key != "binding"
    }:
        return {UNAVAILABLE: UPDATE}
    return compatible_catalog(reply, bound)


def available(selection=None):
    if selection is not None and not selection:
        return {UNAVAILABLE: "routes.inventory.retry"}
    query = {"operation": "catalog"}
    if selection:
        query[inventory.KEY] = selection
    try:
        catalog = client.request(query)
    except inventory.InventoryError as error:
        return {UNAVAILABLE: "routes.ssh.inventory_error", "detail": str(error)}
    except (OSError, ValueError) as error:
        return {UNAVAILABLE: reason(error)}
    return compatible_catalog(catalog, selection)


def compatible_catalog(catalog, selection):
    if catalog.get("ssh_execution") != "automatic":
        return {
            UNAVAILABLE: UPDATE,
            "inventory_files": catalog.get("inventory_files", []),
            "jenkins": catalog.get("jenkins", {}),
        }
    if selection and catalog.get(inventory.KEY) != selection:
        return {UNAVAILABLE: UPDATE}
    return catalog


def reason(error):
    if isinstance(error, FileNotFoundError):
        return "routes.ssh.unavailable"
    if isinstance(error, PermissionError):
        return "routes.ssh.denied"
    return "routes.ssh.unreachable"


def unavailable(catalog):
    reason_key = catalog.get(UNAVAILABLE, "routes.ssh.empty")
    return prompt_texts.text(reason_key, detail=catalog.get("detail", ""))


def protect_sources(config, parent=None):
    """Mask published credential filenames before capturing project files."""
    inventory_inputs.capture(config, (parent or {}).get(inventory_inputs.KEY, ()))
    published = available().get("inventory_files", [])
    protected = config["protected_paths"]
    protected.extend(name for name in inventory_sources.named(config) if name not in protected)
    protected.extend(
        name
        for name in published
        if name not in protected and inventory.NAME_PATTERN.fullmatch(name)
    )
