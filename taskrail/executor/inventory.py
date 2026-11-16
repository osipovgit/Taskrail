"""Resolve literal SSH credentials from a selected static YAML inventory."""

from pathlib import Path

from taskrail.core.files import digest
from taskrail.core.schema import require
from taskrail.executor import inventory_file, inventory_groups, protocol

DIRECTORY = Path("/etc/taskrail-executor/inventories")
KEY = "ssh_inventory"
FILENAME = inventory_file.FILENAME
NAME_PATTERN = inventory_file.NAME_PATTERN
GROUP = "group"
InventoryError = inventory_groups.InventoryError
FIELDS = frozenset((FILENAME, GROUP, "sha256"))
INVALID_DATA = (AttributeError, KeyError, RecursionError, TypeError, ValueError)


def selector(filename, group):
    """An absolute project path or a filename in the private executor catalog."""
    if not filename and not group:
        return None
    if not isinstance(filename, str) or not inventory_file.valid_name(filename):
        raise ValueError("Choose an inventory filename such as servers.yaml and a group")
    return {FILENAME: filename, GROUP: protocol.label(group)}


def checked(selection):
    if not isinstance(selection, dict) or set(selection) - FIELDS:
        raise ValueError("Expected an inventory file and group")
    selection = selector(selection.get(FILENAME), selection.get(GROUP))
    require(selection is not None, "Missing SSH inventory selection")
    return selection


def read(filename, expected):
    """Open without following a symlink or blocking on a special file."""
    require(NAME_PATTERN.fullmatch(filename), "Expected a private inventory filename")
    path = DIRECTORY / filename
    try:
        with inventory_file.opened(path) as descriptor:
            raw = inventory_file.read_descriptor(descriptor)
    except OSError:
        raise InventoryError(
            "Selected inventory file is unavailable to the SSH executor."
        ) from None
    if expected is not None and digest(raw) != expected:
        raise InventoryError("Published inventory differs from the requested project file.")
    return raw


def load(selection, descriptor=None):
    """Return only the selected group's hosts; never include parser errors in responses."""
    selected = checked(selection)
    if inventory_file.project(selected):
        raw = inventory_file.read_descriptor(descriptor)
        if digest(raw) != selection.get("sha256"):
            raise InventoryError("The project inventory changed. Repeat the lookup.")
    else:
        raw = read(selected[FILENAME], selection.get("sha256"))
    document = decoded(raw)
    try:
        return inventory_groups.Groups(document).resolve(selected[GROUP])
    except InventoryError:
        raise
    except INVALID_DATA:
        raise InventoryError(
            "Invalid static SSH inventory or unsupported connection variables."
        ) from None


def decoded(raw):
    """Keep loader diagnostics, which may quote a password, inside the executor."""
    try:
        import yaml
    except ImportError:
        raise InventoryError("Install python3-yaml for the SSH executor.") from None
    try:
        return yaml.safe_load(raw)
    except (RecursionError, ValueError, yaml.YAMLError):
        raise InventoryError("Invalid static YAML inventory.") from None


def inspection_request(payload):
    """Rebuild a selected-inventory action before creating its privileged ticket."""
    from taskrail.executor import action_schema, remote_inspection

    if (KEY in payload) != (payload["operation"] == "inspect-inventory"):
        raise ValueError("Invalid inventory inspection route")
    if KEY in payload:
        action_schema.validate(payload["action"])
        return dict(payload, action=remote_inspection.inspection(payload["action"]))
    return payload


def published():
    """Names alone let the application mask credential files before project discovery."""
    if not DIRECTORY.is_dir():
        return []
    return sorted(
        path.name
        for path in DIRECTORY.iterdir()
        if NAME_PATTERN.fullmatch(path.name) and not path.is_symlink() and path.is_file()
    )
