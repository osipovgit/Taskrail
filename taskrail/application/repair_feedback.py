"""Retry semantic work against the whole artifact and the unresolved set."""

import json
import re

from taskrail.application import check_repeats
from taskrail.core import prompt_texts
from taskrail.core.files import digest

EVIDENCE_IDS = re.compile(r" \(E\d+(?:, E\d+)*\)$")


def identity(version, feedback):
    """Include all outstanding issues; resolving a subset permits another repair."""
    checks = feedback.get("checks")
    if checks is None:
        issues = [issue_set(feedback[key]) for key in ("findings", "blocking_gaps")]
    else:
        issues = sorted(check_repeats.failures(checks))
    return digest(json.dumps([version, issues], sort_keys=True).encode())


def issue_set(entries):
    """Numbering and ordering of findings can change on every independent review."""
    issues = set()
    for entry in entries:
        if isinstance(entry, dict):
            description = EVIDENCE_IDS.sub("", entry["evidence"])
            entry = (entry["criterion"], entry["file"], description)
        issues.add(json.dumps(entry, sort_keys=True))
    return sorted(issues)


def route(flow, state, writer, feedback, version):
    """Compare the entire work product and the outstanding set for this repair route."""
    signature = identity(version, feedback)
    seen = flow.setdefault("repair_states", {}).setdefault(flow["stage"], {})
    count = seen.get(signature, 0)
    seen[signature] = count + 1
    if count >= 2:
        state.update(
            status="NO_PROGRESS",
            summary="The same work and unresolved findings returned after a change of approach.",
        )
        return
    if count:
        feedback = dict(feedback, strategy=prompt_texts.text("recovery.strategy"))
    flow.update(stage=writer, feedback=feedback)


def attach(flow, record):
    """Keep the immutable complete findings available during repair and re-review."""
    if "review_feedback" in record and flow.get("feedback"):
        reference = dict(record["review_feedback"])
        reference.update(
            {key: entry for key, entry in flow["feedback"].items() if key == "strategy"}
        )
        flow["feedback"] = reference
