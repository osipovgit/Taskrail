"""Normalize authored semantic decisions into server-owned stage result fields."""

from taskrail.core import decision_fields, schema
from taskrail.core.decision_evidence import Citations

UNRESOLVED = frozenset(("gap", "not_evaluated"))
ROLE = "role"
IMPLEMENTER = "implementer"


def normalized(payload, context, resolve):
    """V2 carries decisions; canonical V1 stores facts derived at the boundary."""
    schema.validate(payload, schema.SCHEMAS[schema_name(context[ROLE])])
    return Decisions(payload, context, resolve).normalized()


def schema_name(role):
    """The implementer reports outcomes only; reviewers also report findings."""
    return "implementer-decision" if role == IMPLEMENTER else "decision"


class Decisions:
    """Authored assertions and their resolved evidence, before any approval is derived."""

    def __init__(self, payload, context, resolve):
        self.payload = payload
        self.context = context
        self.claims = Citations(resolve)
        requirements = context["requirements"]
        self.rows = [
            decision_fields.outcome(entry, requirements, self.claims)
            for entry in payload["outcomes"]
        ]
        self.defects = [
            decision_fields.finding(entry, requirements, self.claims)
            for entry in payload.get("findings", [])
        ]

    def normalized(self):
        """Produce the canonical record without accepting copied engine facts."""
        gaps = blockers(self.payload, self.rows, self.context)
        verdict = status(self.context[ROLE], gaps, self.defects)
        summary = f"{len(self.rows)} requirement decisions; {len(self.defects)} findings."
        record = dict(
            schema_version=1,
            status=verdict,
            summary=self.payload.get("summary", summary),
            coverage=self.rows,
            evidence=self.claims.entries,
            unverified=decision_fields.deferred(self.rows, self.context["requirements"]),
            blocking_gaps=gaps,
        )
        record.update(role_fields(self.context, verdict, self.defects))
        return record


def blockers(payload, rows, context):
    """Missing inputs and unfinished required work cannot become an approval."""
    gaps = list(payload["missing_inputs"])
    unfinished = set(UNRESOLVED)
    if context["stage"] not in {"planner", "plan-reviewer"}:
        unfinished.add("planned")
    if context[ROLE] == IMPLEMENTER:
        unfinished.add("contradicted")
        schema.require(
            not payload.get("findings"),
            "Implementer reports unresolved outcomes, not review findings",
        )
    missing = [entry for entry in rows if entry["outcome"] in unfinished]
    gaps.extend(entry["explanation"] for entry in missing)
    contradicted = any(entry["outcome"] == "contradicted" for entry in rows)
    schema.require(
        not contradicted or bool(payload.get("findings")) or bool(gaps),
        "Contradicted review needs a finding",
    )
    return gaps


def status(role, gaps, defects):
    """The aggregate verdict is a deterministic reduction of semantic decisions."""
    if gaps:
        return "BLOCKED"
    if role == IMPLEMENTER:
        return "IMPLEMENTED"
    return "REQUEST_CHANGES" if defects else "APPROVE"


def role_fields(context, verdict, defects):
    """Observed changes and approved task identity are never copied by the model."""
    if context[ROLE] == IMPLEMENTER:
        steps = (context.get("plan") or {}).get("steps", [])
        finished = [entry["id"] for entry in steps] if verdict == "IMPLEMENTED" else []
        return dict(completed_steps=finished, changed_files=context["changed"])
    findings = []
    for index, entry in enumerate(defects, 1):
        findings.append(dict(entry, id=f"F{index}"))
    return dict(input_complete=verdict != "BLOCKED", findings=findings)
