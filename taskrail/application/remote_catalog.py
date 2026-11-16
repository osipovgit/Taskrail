"""Discover the selected executor targets without exposing authentication data."""

from taskrail.core import prompt_texts
from taskrail.executor import client, inventory

UNAVAILABLE = "unavailable"


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
    if selection and catalog.get(inventory.KEY) != selection:
        return {UNAVAILABLE: "routes.ssh.update"}
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


def protect_sources(config):
    """Mask published credential filenames before capturing project files."""
    published = available().get("inventory_files", [])
    protected = config["protected_paths"]
    protected.extend(
        name
        for name in published
        if name not in protected and inventory.NAME_PATTERN.fullmatch(name)
    )
