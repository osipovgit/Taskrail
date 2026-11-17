"""Ansible configuration values relevant to direct SSH; inventory variables take precedence."""

from types import MappingProxyType

from taskrail.executor import inventory_connection

BASE = MappingProxyType(
    {
        "DEFAULT_TRANSPORT": "ansible_connection",
        "DEFAULT_REMOTE_USER": "ansible_user",
        "DEFAULT_REMOTE_PORT": "ansible_port",
        "DEFAULT_PRIVATE_KEY_FILE": "ansible_private_key_file",
    }
)
SSH = MappingProxyType(
    {
        "remote_user": "ansible_user",
        "port": "ansible_port",
        "password": "ansible_password",
        "private_key_file": "ansible_private_key_file",
        "ssh_args": "ansible_ssh_args",
        "ssh_common_args": "ansible_ssh_common_args",
        "ssh_extra_args": "ansible_ssh_extra_args",
        "ssh_executable": "ansible_ssh_executable",
    }
)
ALIASES = MappingProxyType({names[0]: names for names in inventory_connection.CONNECTION.values()})
FIELDS = frozenset(name for names in ALIASES.values() for name in names).union(
    inventory_connection.SSH_OVERRIDES, {"ansible_connection"}
)


def parse(rows, mapping):
    if not isinstance(rows, list):
        raise inventory_connection.InventoryError("Invalid ansible-config output.")
    defaults = {}
    for row in rows:
        if isinstance(row, dict) and row.get("value") is not None:
            key = mapping.get(row.get("name"))
            if key is not None:
                defaults[key] = row["value"]
    return defaults


def configured(command, source):
    argv = ["ansible-config", "dump", "--only-changed", "--format", "json"]
    defaults = parse(command(argv, source), BASE)
    plugins = command([*argv, "-t", "connection", "ssh"], source)
    if not isinstance(plugins, list):
        raise inventory_connection.InventoryError("Invalid SSH plugin configuration output.")
    for plugin in plugins:
        if isinstance(plugin, dict):
            defaults.update(parse(plugin.get("ssh", []), SSH))
    return defaults


def host_settings(variables, defaults):
    settings = {key: entry for key, entry in variables.items() if key in FIELDS}
    for key, entry in defaults.items():
        aliases = ALIASES.get(key, (key,))
        if settings.keys().isdisjoint(aliases):
            settings[key] = entry
    return settings
