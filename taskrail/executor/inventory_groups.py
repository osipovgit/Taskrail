"""Membership and connection variables from a static Ansible YAML groups graph."""

from graphlib import CycleError, TopologicalSorter
from types import MappingProxyType

from taskrail.core.schema import require
from taskrail.executor import hosts, protocol

CONNECTION = MappingProxyType(
    {
        "hostname": ("ansible_host", "ansible_ssh_host"),
        "username": ("ansible_user", "ansible_ssh_user"),
        hosts.PASSWORD: ("ansible_password", "ansible_ssh_pass", "ansible_ssh_password"),
        hosts.PORT: ("ansible_port", "ansible_ssh_port"),
    }
)
ALL = "all"
SSH_PORT = 22
SSH_OVERRIDES = frozenset(
    (
        "ansible_ssh_common_args",
        "ansible_ssh_extra_args",
        "ansible_ssh_args",
        "ansible_ssh_executable",
        "ansible_ssh_private_key_file",
        "ansible_private_key_file",
    )
)


class InventoryError(ValueError):
    """Only fixed diagnostics without YAML snippets can leave the executor."""


class Groups:
    """Collect every parent before computing inherited variables for selected hosts."""

    def __init__(self, document):
        self.parents = {ALL: set()}
        self.variables = {}
        self.members = {}
        self.hostvars = {}
        self._seen = set()
        for name, group in document.items():
            self.collect(name, group, None)
        self.lineage = self.ancestry()

    def collect(self, name, group, parent):
        protocol.label(name)
        self.parents.setdefault(name, set())
        if parent is not None:
            self.parents[name].add(parent)
        marker = (name, id(group))
        if group is None or marker in self._seen:
            return
        self._seen.add(marker)
        require(set(group) <= {"hosts", "vars", "children"}, "Unsupported inventory group")
        variables = self.variables.setdefault(name, {})
        variables.update(group.get("vars") or {})
        self.collect_hosts(name, group.get("hosts") or {})
        for child, definition in (group.get("children") or {}).items():
            self.collect(child, definition, name)

    def collect_hosts(self, group, definitions):
        for alias, settings in definitions.items():
            protocol.label(alias)
            self.members.setdefault(alias, set()).add(group)
            self.hostvars.setdefault(alias, {}).update(settings or {})

    def ancestry(self):
        lineage = {}
        self.depth = {}
        for group in group_order(self.parents):
            ancestors = self.parents[group]
            lineage[group] = {group}.union(*map(lineage.__getitem__, ancestors))
            deepest = max(map(self.depth.__getitem__, ancestors), default=0)
            self.depth[group] = deepest + 1
        return lineage

    def resolve(self, group):
        if group not in self.parents:
            raise InventoryError("The selected group is absent from this inventory.")
        found = {}
        for alias, direct in self.members.items():
            inherited = set().union(*map(self.lineage.__getitem__, direct))
            if group in inherited:
                found[alias] = self.connection(alias, inherited)
        if not found:
            raise InventoryError("The selected SSH inventory group contains no hosts.")
        return found

    def precedence(self, name):
        priority = self.variables.get(name, {}).get("ansible_group_priority", 1)
        return self.depth[name], int(priority), name

    def connection(self, alias, inherited):
        """Merge parents before children and apply host variables last."""
        settings = {}
        for name in sorted(inherited, key=self.precedence):
            settings.update(self.variables.get(name, {}))
        settings.update(self.hostvars[alias])
        return connection(alias, settings)


def group_order(parents):
    for name, inherited in parents.items():
        if name != ALL and not inherited:
            inherited.add(ALL)
    try:
        return tuple(TopologicalSorter(parents).static_order())
    except CycleError:
        raise InventoryError("SSH inventory groups contain a cycle.") from None


def connection(alias, settings):
    """Only direct SSH and literal fields reach the existing password transport."""
    require(settings.get("ansible_connection", "ssh") in ("ssh", "smart"), "Expected SSH")
    require(not any(settings.get(key) for key in SSH_OVERRIDES), "Unsupported SSH overrides")
    host = connection_fields(settings)
    host.setdefault("hostname", alias)
    port = host.setdefault(hosts.PORT, SSH_PORT)
    if isinstance(port, str) and port.isdecimal():
        host[hosts.PORT] = int(port)
    hosts.validate(host)
    password = host[hosts.PASSWORD]
    require(
        not any(marker in password for marker in ("{{", "{%", "{#", "$ANSIBLE_VAULT;")),
        "Expected a literal password",
    )
    return host


def connection_fields(settings):
    host = {}
    for field, names in CONNECTION.items():
        for name in names:
            if name in settings:
                host[field] = settings.get(name)
                break
    return host
