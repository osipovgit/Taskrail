"""The words of a review.md requirement line and what each one needs."""

from types import MappingProxyType

from taskrail.core.plan_outcomes import PLACEHOLDER

SATISFIED = "satisfied"
CONTRADICTED = "contradicted"
GAP = "gap"
DEFERRED = "deferred"
NOT_APPLICABLE = "not_applicable"
PLANNED = "planned"
EXPLANATION = "explanation"
KINDS = MappingProxyType(
    {
        "done": SATISFIED,
        "fails": CONTRADICTED,
        GAP: GAP,
        "n/a": NOT_APPLICABLE,
        "later": DEFERRED,
        "runtime": DEFERRED,
        PLANNED: PLANNED,
    }
)
CITED = frozenset((SATISFIED, CONTRADICTED))
EXPLAINED = frozenset((CONTRADICTED, GAP, NOT_APPLICABLE))
PLAN_REVIEW = "plan-reviewer"


def classify(text, stage):
    """(outcome, detail) of a line's text, or None when it names no allowed outcome."""
    word, _, detail = text.partition(":")
    kind = KINDS.get(word.strip().casefold())
    if kind is None or PLACEHOLDER.match(text):
        return None
    if kind == PLANNED and stage != PLAN_REVIEW:
        return None
    return kind, detail.strip()


def prefix(stage, number):
    """Scope fresh plan finding IDs to their originating review attempt."""
    return f"F{number}-" if stage == PLAN_REVIEW else "F"


def combine(rows, label, row, stage):
    """Aggregate distinct plan defects without weakening single-outcome coverage."""
    previous = rows.get(label)
    if previous is None:
        rows[label] = row
        return True
    failures = previous["outcome"] == row["outcome"] == CONTRADICTED
    if stage != PLAN_REVIEW or not failures:
        return False
    previous["evidence_ids"] = [*previous["evidence_ids"], *row["evidence_ids"]]
    previous[EXPLANATION] = "\n".join((previous[EXPLANATION], row[EXPLANATION]))
    return True


def numbered(findings, prefix):
    """Findings with their F<n> identities."""
    numbered_findings = enumerate(findings, 1)
    return [
        dict(entry, id=entry.get("id", f"{prefix}{index}")) for index, entry in numbered_findings
    ]


def finding(requirement, path, explanation, identifiers):
    """A failure of one requirement at its first cited file."""
    cited = ", ".join(identifiers)
    described = f"{explanation} ({cited})"
    return dict(criterion=requirement, file=path, evidence=described)


def labels(rows):
    """The `R<n>` labels the explanations of stored review rows start with, comma-separated."""
    explanations = (row[EXPLANATION] for row in rows)
    return ", ".join(stated.partition(":")[0] for stated in explanations)
