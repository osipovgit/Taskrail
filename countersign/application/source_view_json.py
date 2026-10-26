"""Reindent strict JSON without changing scalar spelling or discarding values."""

import json
import re

from countersign.core.schema import require, unique_fields

TOKENS = re.compile(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]|[^\s{}\[\],:]+')
MAX_BYTES = 33554432
MAX_LINE = 1500


def formatted(text):
    """Return bounded, lossless JSON text; invalid or unreadable values are rejected."""
    json.loads(
        text,
        object_pairs_hook=unique_fields,
        parse_int=str,
        parse_float=str,
        parse_constant=reject_constant,
    )
    pieces = []
    remaining = MAX_BYTES - 1
    for piece in fragments(text):
        remaining -= len(piece.encode("utf-8"))
        require(remaining >= 0, "Formatted JSON exceeds the source view size limit")
        pieces.append(piece)
    rendered = "{}\n".format("".join(pieces))
    require(
        all(len(line) <= MAX_LINE for line in rendered.splitlines()),
        "A JSON scalar exceeds the source view line limit",
    )
    return rendered


def reject_constant(token):
    """Non-finite JavaScript constants are not JSON values."""
    raise ValueError(f"Non-finite JSON constant: {token}")


def fragments(text):
    """Change whitespace only outside quoted strings in an already validated document."""
    depth = 0
    for match in TOKENS.finditer(text):
        symbol = match[0]
        if symbol in {"}", "]"}:
            depth -= 1
            yield "\n{}".format("  " * depth)
        yield symbol
        if symbol in {"{", "["}:
            depth += 1
            yield "\n{}".format("  " * depth)
        elif symbol == ",":
            yield "\n{}".format("  " * depth)
        elif symbol == ":":
            yield " "
