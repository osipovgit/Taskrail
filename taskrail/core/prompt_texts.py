"""Read the release's model-facing texts once and render their placeholders."""

import json
from pathlib import Path
from string import Template
from types import MappingProxyType


def load():
    """Keep the catalog's strings and line sequences immutable."""
    path = Path(__file__).with_name("prompt-texts.json")
    entries = json.loads(path.read_text(encoding="utf-8"))
    for key, entry in entries.items():
        if isinstance(entry, list):
            entries[key] = tuple(entry)
    return MappingProxyType(entries)


ENTRIES = load()


def text(key, **fields):
    """One release text with its placeholders filled in; missing values are errors."""
    entry = ENTRIES[key]
    if isinstance(entry, tuple):
        entry = "\n".join(entry)
    return Template(entry).substitute(fields)
