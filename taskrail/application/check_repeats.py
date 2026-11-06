"""Identify the complete set of failing checks, independent of volatile log metadata."""

import re

FAIL = "FAIL"
VARYING = re.compile(r"evidence \S+|\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds)\b")


def failures(checks):
    """Match the command, directory and diagnostic of every failing check."""
    found = set()
    for check in checks:
        if check.get("status") != FAIL:
            continue
        detail = str(check.get("detail", ""))
        name = str(check.get("file", ""))
        directory = check.get("cwd", "")
        found.add((name, directory, VARYING.sub("", detail)))
    return frozenset(found)
