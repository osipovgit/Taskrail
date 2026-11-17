"""Membership and connection variables from a static Ansible YAML groups graph."""

from graphlib import CycleError, TopologicalSorter

from taskrail.executor import protocol
from taskrail.executor.inventory_connection import InventoryError, bind

ALL = "all"


def mapping(entry, section):
    if entry is None:
        return {}
    if not isinstance(entry, dict):
        raise InventoryError(f"Expected a YAML mapping for {section}.")
    return entry


def identifier(name, kind):
    try:
        protocol.label(name)
    except ValueError:
        raise InventoryError(
            f"Invalid {kind}. Use a literal name starting with a letter or digit, "
            "containing only ASCII letters, digits, dots, underscores or hyphens."
        ) from None


class Groups:
    """Collect every parent before computing inherited variables for selected hosts."""

    def __init__(self, document):
        self.parents = {ALL: set()}
        self.variables = {}
        self.members = {}
        self.hostvars = {}
        self._seen = set()
        for name, group in mapping(document, "the inventory").items():
            self.collect(name, group, None)
        self.lineage = self.ancestry()

    def collect(self, name, group, parent):
        identifier(name, "group name")
        self.parents.setdefault(name, set())
        if parent is not None:
            self.parents[name].add(parent)
        marker = (name, id(group))
        if group is None or marker in self._seen:
            return
        self._seen.add(marker)
        group = mapping(group, "a group")
        if set(group) - {"hosts", "vars", "children"}:
            raise InventoryError("A static inventory group accepts only hosts, vars and children.")
        variables = self.variables.setdefault(name, {})
        variables.update(mapping(group.get("vars"), "group vars"))
        self.collect_hosts(name, mapping(group.get("hosts"), "hosts"))
        for child, definition in mapping(group.get("children"), "children").items():
            self.collect(child, definition, name)

    def collect_hosts(self, group, definitions):
        for alias, settings in definitions.items():
            identifier(alias, "host alias")
            self.members.setdefault(alias, set()).add(group)
            self.hostvars.setdefault(alias, {}).update(mapping(settings, "host variables"))

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
            if group not in inherited:
                continue
            found[alias] = self.connection(alias, inherited, len(found) + 1)
        if not found:
            raise InventoryError("The selected SSH inventory group contains no hosts.")
        return found

    def precedence(self, name):
        priority = self.variables.get(name, {}).get("ansible_group_priority", 1)
        try:
            return self.depth[name], int(priority), name
        except (TypeError, ValueError, OverflowError):
            raise InventoryError("ansible_group_priority must be an integer.") from None

    def connection(self, alias, inherited, position):
        """Merge parents before children and apply host variables last."""
        settings = {}
        for name in sorted(inherited, key=self.precedence):
            settings.update(self.variables.get(name, {}))
        settings.update(self.hostvars[alias])
        try:
            return bind(alias, settings)
        except InventoryError as error:
            raise InventoryError(f"Selected host #{position}: {error}") from None


def group_order(parents):
    for name, inherited in parents.items():
        if name != ALL and not inherited:
            inherited.add(ALL)
    try:
        return tuple(TopologicalSorter(parents).static_order())
    except CycleError:
        raise InventoryError("SSH inventory groups contain a cycle.") from None
