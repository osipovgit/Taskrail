"""Model-facing instruction texts: one release catalog, frozen for each run.

Every instruction a model reads comes from prompt-texts.json. A run freezes the
catalog with its contract, and continuing the run adopts that frozen copy, so an
update of the application never changes the instructions of a running task.
"""

import json
from pathlib import Path
from string import Template

CATALOG = Path(__file__).with_name("prompt-texts.json")


def release():
    """The catalog of this release: key -> text or list of lines."""
    return json.loads(CATALOG.read_text(encoding="utf-8"))


class Catalog:
    """The texts of the running workflow: the release catalog or a run's frozen copy."""

    def __init__(self, entries):
        """Start with the given entries."""
        self.entries = dict(entries)

    def adopt(self, entries):
        """Use a run's frozen texts from now on."""
        self.entries = dict(entries)

    def text(self, key, **fields):
        """One text with its $placeholders filled in; a missing value is an error."""
        entry = self.entries[key]
        if isinstance(entry, list):
            entry = "\n".join(entry)
        return Template(entry).substitute(fields)


ACTIVE = Catalog(release())


def text(key, **fields):
    """A text of the active catalog."""
    return ACTIVE.text(key, **fields)
