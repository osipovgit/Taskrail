"""Keep the repair round's immutable review reference across retries and reinterpretation."""

import re
from pathlib import Path

from taskrail.application import reviewed_artifacts
from taskrail.core.schema import require

ROUND = re.compile(r"\d+-plan-review")


def packet(feedback):
    """Continue may wrap the review packet in an operator note."""
    while isinstance(feedback, dict):
        name = feedback.get("findings_file")
        if name and ROUND.fullmatch(Path(name).parent.name):
            return feedback
        feedback = feedback.get("previous_feedback")
    return None


def pending(run, feedback):
    """Use the exact review named by the checkpoint, even if a later attempt finished."""
    found = packet(feedback)
    if found is None:
        return []
    path = Path(found["findings_file"])
    require(path.parent.parent == run and path.name == "findings.json", "Invalid review reference")
    reference = path.relative_to(run).with_name("result.json")
    require(path.parent.resolve() == path.parent, "Invalid review directory")
    return reviewed_artifacts.document(run, reference)["findings"]
