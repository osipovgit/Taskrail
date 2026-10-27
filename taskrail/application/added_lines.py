"""Scan the lines a change added for secrets and leftover debugging; nothing is executed.

Each approved file is compared with its preimage; line_findings judges the lines the
change inserted or replaced. A file without findings adds no record.
"""

import difflib

from taskrail.application import line_findings
from taskrail.application.planned_paths import safe_file

NUL = b"\0"
EQUAL = "equal"


def scan(run, roots, preimages):
    """FAIL and WARN records of the approved files' added lines."""
    records = []
    for name, stored in preimages.items():
        path = safe_file(name, roots)
        if path.is_file():
            lines = added(run, path, stored)
            records.extend(line_findings.records(name, lines, path.suffix))
    return records


def added(run, path, stored):
    """(line number, text) of each line the current file adds to its preimage."""
    before = run.joinpath(stored).read_bytes() if stored else b""
    after = path.read_bytes()
    if NUL in before or NUL in after:
        return []
    return inserted(decoded_lines(before), decoded_lines(after))


def decoded_lines(encoded):
    """Lines of leniently decoded bytes."""
    return encoded.decode(errors="replace").splitlines()


def inserted(old, new):
    """The new lines that inserting and replacing opcodes produce, numbered from 1."""
    opcodes = difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes()
    spans = [opcode[3:] for opcode in opcodes if opcode[0] != EQUAL]
    numbers = [number for start, end in spans for number in range(start, end)]
    return [(number + 1, new[number]) for number in numbers]
