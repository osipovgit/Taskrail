"""Secrets and leftover debugging in added lines.

A private key, an access token or an API key fails the check, so the implementer
removes it before review. A literal assigned to a secret-like name and leftover
debugging statements are warnings the review sees. A finding names the line and the
kind, never the matched text.
"""

import re
from types import MappingProxyType

FAIL = "FAIL"
WARN = "WARN"
LINE = "line {0}: {1}"
SECRETS = MappingProxyType(
    {
        "a private key": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
        "a GitHub token": re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{36,}"),
        "an AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "an API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
        "a Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    }
)
ASSIGNED = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key)\w*[\"']?\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
)
TEMPLATED = re.compile(r"\{\{|\$\{|\$\(|%\(")
SCRIPT_DEBUG = re.compile(r"\bconsole\.log\(|^\s*debugger;?\s*$")
DEBUG = MappingProxyType(
    {
        ".py": re.compile(r"\bbreakpoint\(\)|\bi?pdb\.set_trace\(|^\s*import i?pdb\b"),
        ".js": SCRIPT_DEBUG,
        ".jsx": SCRIPT_DEBUG,
        ".mjs": SCRIPT_DEBUG,
        ".cjs": SCRIPT_DEBUG,
        ".ts": SCRIPT_DEBUG,
        ".tsx": SCRIPT_DEBUG,
        ".vue": SCRIPT_DEBUG,
    }
)


def records(name, lines, suffix):
    """At most one FAIL and one WARN record for a file's added lines."""
    failures = findings(lines, secret_kind)
    warnings = findings(lines, lambda text: warning_kind(text, suffix))
    found = []
    if failures:
        found.append(record(name, FAIL, failures, "remove it; read secrets from configuration"))
    if warnings:
        found.append(record(name, WARN, warnings, "the review decides whether it stays"))
    return found


def findings(lines, kind_of):
    """Line number -> kind, for each added line that matches."""
    found = {}
    for number, text in lines:
        kind = kind_of(text)
        if kind:
            found[number] = kind
    return found


def secret_kind(text):
    """The kind of credential an added line contains, or None."""
    for kind, pattern in SECRETS.items():
        if pattern.search(text):
            return kind
    return None


def warning_kind(text, suffix):
    """A secret-like literal or leftover debugging statement, or None."""
    assigned = ASSIGNED.search(text)
    if assigned and not TEMPLATED.search(assigned.group(1)):
        return "a literal assigned to a secret-like name"
    debug = DEBUG.get(suffix)
    if debug and debug.search(text):
        return "leftover debugging"
    return None


def record(name, status, found, advice):
    """One check record naming each line and its kind."""
    entries = [LINE.format(*entry) for entry in sorted(found.items())]
    listed = "; ".join(entries)
    return dict(file=name, status=status, detail=f"Added {listed}; {advice}")
