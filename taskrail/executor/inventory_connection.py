"""Bind the static connection fields understood by the isolated SSH transport."""

from types import MappingProxyType

from taskrail.executor import hosts

CONNECTION = MappingProxyType(
    {
        "hostname": ("ansible_host", "ansible_ssh_host"),
        "username": ("ansible_user", "ansible_ssh_user"),
        hosts.PASSWORD: ("ansible_password", "ansible_ssh_pass", "ansible_ssh_password"),
        hosts.PORT: ("ansible_port", "ansible_ssh_port"),
    }
)
SSH_PORT = 22
SSH_OVERRIDES = (
    "ansible_ssh_common_args",
    "ansible_ssh_extra_args",
    "ansible_ssh_args",
    "ansible_ssh_executable",
    "ansible_ssh_private_key_file",
    "ansible_private_key_file",
)


class InventoryError(ValueError):
    """Only fixed diagnostics without YAML snippets can leave the executor."""


def bind(alias, settings):
    """Only direct SSH and literal fields reach the existing password transport."""
    check_transport(settings)
    host = connection_fields(settings)
    host.setdefault("hostname", alias)
    host[hosts.PORT] = port_number(host.get(hosts.PORT, SSH_PORT))
    try:
        hosts.validate(host)
    except hosts.InvalidConnection as error:
        raise InventoryError(str(error)) from None
    return host


def check_transport(settings):
    if settings.get("ansible_connection", "ssh") not in ("ssh", "smart"):
        raise InventoryError("ansible_connection must select ssh or smart.")
    for key in SSH_OVERRIDES:
        if settings.get(key):
            raise InventoryError(f"The direct SSH executor does not support {key}.")


def port_number(port):
    if isinstance(port, str) and port.isdecimal():
        try:
            return int(port)
        except ValueError:
            raise InventoryError("ansible_port must be an integer between 1 and 65535.") from None
    return port


def connection_fields(settings):
    host = {}
    for field, names in CONNECTION.items():
        name = next((key for key in names if key in settings), None)
        if name is not None:
            host[field] = literal(name, settings[name])
        if field in ("username", hosts.PASSWORD) and host.get(field) is None:
            raise InventoryError(
                f"Missing {names[0]}. The static inventory must supply it in host or group variables."
            )
    return host


def literal(name, entry):
    markers = ("{{", "{%", "{#", "$ANSIBLE_VAULT;")
    if isinstance(entry, str) and any(marker in entry for marker in markers):
        raise InventoryError(f"{name} must be literal. Templates and Vault are unsupported.")
    return entry
