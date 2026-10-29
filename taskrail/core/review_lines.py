"""The words of a review.md requirement line and what each one needs."""

from types import MappingProxyType

from taskrail.core.plan_outcomes import PLACEHOLDER

SATISFIED = "satisfied"
CONTRADICTED = "contradicted"
GAP = "gap"
DEFERRED = "deferred"
NOT_APPLICABLE = "not_applicable"
PLANNED = "planned"
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


def parenthesized(detail):
    """The explanation in parentheses after a citation list, or empty."""
    opened = detail.find("(")
    if opened < 0:
        return ""
    return detail[opened + 1 : detail.rfind(")")].strip()


def numbered(findings):
    """Findings with their F<n> identities."""
    numbered_findings = enumerate(findings, 1)
    return [dict(entry, id=f"F{index}") for index, entry in numbered_findings]


def finding(requirement, path, explanation, identifiers):
    """A failure of one requirement at its first cited file."""
    cited = ", ".join(identifiers)
    described = f"{explanation} ({cited})"
    return dict(criterion=requirement, file=path, evidence=described)
