"""Resolve concise references into canonical, independently validated citations."""

import re

from countersign.core import schema

REFERENCE = re.compile(r"(.+):(\d+)(?:-(\d+))?\Z")


class Citations:
    """Deduplicate references; handles are resolved by the application boundary."""

    def __init__(self, resolve):
        self.resolve = resolve
        self.entries = []
        self.known = {}

    def collect(self, references):
        """Return stable IDs for the supplied source ranges, preserving order."""
        return list(dict.fromkeys(self.reference(reference) for reference in references))

    def reference(self, reference):
        """A source path or server handle followed by a complete line range."""
        identifier = self.known.get(reference)
        if identifier:
            return identifier
        claim = parsed(reference)
        span = (claim["path"], claim["line_start"], claim["line_end"])
        claim["path"] = self.resolve(*span)
        number = len(self.entries) + 1
        identifier = f"E{number}"
        self.entries.append(dict(claim, id=identifier))
        self.known[reference] = identifier
        return identifier


def parsed(reference):
    """Parse the full citation, rejecting malformed tails and reversed positions."""
    match = REFERENCE.fullmatch(reference)
    schema.require(bool(match), f"Invalid evidence reference: {reference}; use path:from-to")
    start = int(match[2])
    end = int(match[3] or match[2])
    schema.require(0 < start <= end, "Invalid evidence line range")
    return dict(path=match[1], line_start=start, line_end=end)
