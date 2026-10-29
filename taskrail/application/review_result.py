"""A reviewer's stage result: review.md read by the server, with resolved citations.

A citation names an absolute path, a project path or a delivered source handle such
as S1:10-12. When the session has no corrections left, a requirement whose citations
it never confirmed becomes a gap naming that instead of failing the stage. The
accepted review.md is kept beside the attempt.
"""

import re
import shutil
from functools import partial
from pathlib import Path

from taskrail.application import citation_review, review_file, source_packet
from taskrail.core import prompt_texts, review_document
from taskrail.core.plan_outcomes import absolute

SOURCE_HANDLE = re.compile(r"S\d+")
GAP = "gap"
REVIEWS = frozenset(("plan-reviewer", "reviewer"))


def stage_result(context):
    """The review result of review.md; ValueError names its problems by line."""
    target = review_file.path(context["run"])
    written = target.read_text(encoding="utf-8") if target.is_file() else ""
    resolve = partial(resolve_reference, context)
    record = review_document.payload(written, context["requirements"], context["stage"], resolve)
    shutil.copyfile(target, context["folder"] / review_file.NAME)
    return record


def resolve_reference(context, name, start, end):
    """An absolute path, a delivered source handle or a path in the roots."""
    if Path(name).is_absolute():
        return name
    if SOURCE_HANDLE.fullmatch(name):
        return source_packet.resolve(name, start, end, context)
    return absolute(name, context["roots"])


def settled(record, records, context):
    """A review without corrections left keeps its confirmed claims only."""
    if context["stage"] not in REVIEWS or context["deliver_lines"]:
        return record
    return downgraded(record, records, context)


def downgraded(record, records, context):
    """Requirements whose citations the session never confirmed become gaps."""
    failing = refuted(record["evidence"], records, context)
    if not failing:
        return record
    suffix = " ({})".format(prompt_texts.text("review.unconfirmed"))
    for row in record["coverage"]:
        if failing.intersection(row["evidence_ids"]):
            row.update(outcome=GAP, evidence_ids=[])
            row["explanation"] += suffix
    return recounted(record, failing)


def recounted(record, failing):
    """Evidence, findings, gaps and verdict after some requirements became gaps."""
    claims = [claim for claim in record["evidence"] if claim["id"] not in failing]
    rows = record["coverage"]
    gaps = [row["explanation"] for row in rows if row["outcome"] == GAP]
    record = dict(record, evidence=claims, blocking_gaps=gaps, findings=still_failed(record))
    status = review_document.verdict(gaps, record["findings"])
    return dict(record, status=status, input_complete=status != "BLOCKED")


def still_failed(record):
    """The findings whose requirements still fail."""
    rows = record["coverage"]
    failed = {row["id"] for row in rows if row["outcome"] == "contradicted"}
    return [entry for entry in record["findings"] if entry["criterion"] in failed]


def refuted(claims, records, context):
    """IDs of the citations that fail their source check."""
    failing = set()
    for claim in claims:
        try:
            citation_review.checked(claim, records, context)
        except ValueError:
            failing.add(claim["id"])
    return failing
