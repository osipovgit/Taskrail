"""Bind every planner response and independent review decision to an issued finding."""

import re

from taskrail.core import prompt_texts

RESPONSES = "finding_responses"
CHECKS = "finding_checks"
ID = re.compile(r"F[1-9]\d*(?:-[1-9]\d*)?\Z")


def parse(lines, allowed):
    """Read ID: decision: detail, preserving the full explanation and its source line."""
    decisions = {}
    for line, number in lines:
        decision = parsed(line, number, allowed)
        name = decision["id"]
        if name in decisions:
            raise ValueError(prompt_texts.text("finding.duplicate", line=number, id=name))
        decisions[name] = decision
    return decisions


def parsed(line, number, allowed):
    """Read a single labelled decision and keep colons inside its reasoning."""
    parts = [word.strip() for word in line.split(":", 2)]
    if len(parts) != 3 or not valid(parts, allowed):
        raise ValueError(
            prompt_texts.text("finding.format", line=number, choices=" or ".join(allowed))
        )
    name, status, detail = parts
    return dict(id=name, status=status.lower(), reason=detail)


def store_responses(lines, found):
    """A planner only adds this section in response to an independent review."""
    responses = parse(lines, ("fixed", "disputed"))
    if responses:
        found[RESPONSES] = list(responses.values())


def valid(parts, allowed):
    """Require the issued ID syntax, a known action and a nonempty reason."""
    name, action, detail = parts
    return ID.fullmatch(name) and action.lower() in allowed and detail


def complete(decisions, prior):
    """Unknown, missing and closed IDs cannot substitute for an outstanding one."""
    expected = {entry["id"] for entry in prior}
    missing = expected.difference(decisions)
    unknown = set(decisions).difference(expected)
    if missing or unknown:
        raise ValueError(
            prompt_texts.text(
                "finding.incomplete",
                missing=", ".join(sorted(missing)) or "none",
                unknown=", ".join(sorted(unknown)) or "none",
            )
        )
