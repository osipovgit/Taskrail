"""The index at the top of recovery.md: what each recorded output is and where it is.

A model reads the index first and then only the blocks it needs, because the whole
file can be larger than its context.
"""

import json

RULE = "Read only the blocks you need, at most 200 lines at a time; never read this file whole."
HEAD = ("", "## Index", RULE)
WINDOW_KEYS = ("pattern", "offset", "limit")


def index_lines(records, blocks, start):
    """The index after line start: one entry per record with the lines of its block."""
    spans = block_spans(blocks, start + len(HEAD) + len(records))
    entries = list(HEAD)
    for number, pair in enumerate(zip(records, spans), 1):
        entries.append(index_entry(number, *pair))
    return entries


def block_spans(blocks, end):
    """Lines of each block from its heading to its END marker; the blocks follow line end."""
    spans = []
    for block in blocks:
        spans.append((end + 2, end + text_lines(block)))
        end = spans[-1][1]
    return spans


def text_lines(block):
    """Lines a block occupies once written; outputs may span many lines."""
    return sum(text.count("\n") + 1 for text in block)


def index_entry(number, record, span):
    """Tool, target and window, size, and the lines of its block."""
    arguments = record["input"]
    target = arguments.get("filePath") or arguments.get("path") or ""
    present = [key for key in WINDOW_KEYS if key in arguments]
    window = json.dumps({key: arguments[key] for key in present})
    where = "{0} characters · lines {1}-{2}".format(record["saved_chars"], *span)
    return "{0}. {1} {2} {3} · {4}".format(number, record["tool"], target, window, where)
