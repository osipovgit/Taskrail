"""Classify task-named YAML versions without including their contents in run artifacts."""

import re
from functools import cache, partial
from subprocess import TimeoutExpired

from taskrail.core.git_marker import control
from taskrail.executor import inventory_file, inventory_groups
from taskrail.git import process

PASSWORD_FIELDS = tuple(
    name.encode()
    for name in (
        *inventory_groups.CONNECTION["password"],
        "ansible_become_pass",
        "ansible_sudo_pass",
    )
)
ESCAPED_KEY = re.compile(rb"\\(?:[xuU]|[\r\n])")


def private(path):
    try:
        with inventory_file.opened(path) as stream:
            raw = inventory_file.read_descriptor(stream.fileno())
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    return sensitive(raw)


def sensitive(raw):
    # YAML may encode a literal key with Unicode escapes or a continued quoted scalar.
    if b"\x00" in raw or ESCAPED_KEY.search(raw):
        return True
    return any(field in raw for field in PASSWORD_FIELDS)


def hidden(root, names):
    """Check working files first, then the index and committed versions used at launch."""
    masked = {name for name in names if private(root / name)}
    remaining = names - masked
    if remaining and control(root / ".git"):
        try:
            masked.update(git_private(root, remaining))
        except (OSError, TimeoutExpired):
            masked.update(remaining)
    return masked


def queries_for(names):
    for name in names:
        # The Git batch protocol uses LF as delimiter. Keep unusual names masked.
        if "\n" not in str(name) and "\r" not in str(name):
            for ref in ("HEAD", ":0"):
                yield f"{ref}:{name}", name


def batch(root, queries):
    entries = "".join(f"{query}\n" for query in queries)
    records = process.invoke(root, ["cat-file", "--batch-check"], input_data=entries.encode())
    lines = records.stdout.split("\n")[:-1]
    if records.returncode or len(lines) != len(queries):
        return None
    return zip(queries, lines, strict=True)


def git_private(root, names):
    queries = dict(queries_for(names))
    rows = batch(root, queries)
    if rows is None:
        yield from names
        return
    yield from names.difference(queries.values())
    verdict = cache(partial(private_blob, root))
    for query, line in rows:
        if line != f"{query} missing" and verdict(line):
            yield queries[query]


def private_blob(root, record):
    metadata = re.fullmatch(r"([0-9a-f]+) blob ([0-9]+)", record)
    if not metadata or int(metadata[2]) > inventory_file.MAX_BYTES:
        return True
    raw = process.blob(root, metadata[1])
    if raw is None or len(raw) != int(metadata[2]):
        return True
    return sensitive(raw)
