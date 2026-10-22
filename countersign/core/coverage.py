"""Validate requirement ownership and review decisions, independently of prose."""

from countersign.core.schema import require

OUTCOME = "outcome"
STATUS = "status"
IDENTIFIER = "id"
PLANNING = frozenset(("planner", "plan-reviewer"))


def unique(entries, label):
    """Return indexed records while rejecting duplicate identifiers."""
    indexed = {entry[IDENTIFIER]: entry for entry in entries}
    require(len(indexed) == len(entries), f"Duplicate {label}")
    return indexed


def validate_coverage(payload, requirements, stage, executed_evidence=(), planned_runtime=()):
    """Every supplied requirement must have a justified, stage-appropriate outcome."""
    outcomes = unique(payload["coverage"], "coverage ID")
    check_ids(set(outcomes), {entry[IDENTIFIER] for entry in requirements})
    evidence = unique(payload["evidence"], "evidence ID")
    permitted = planned_runtime if stage in PLANNING else ()
    for entry in requirements:
        validate_outcome(outcomes[entry[IDENTIFIER]], entry, evidence, executed_evidence, permitted)
    validate_findings(payload.get("findings", []), outcomes)
    verdicts(payload, stage)


def check_ids(covered, expected):
    """Coverage names exactly the assigned requirement IDs."""
    missing = sorted(expected - covered)
    unknown = sorted(covered - expected)
    require(
        not missing and not unknown,
        f"Incomplete requirement coverage: missing {missing}, unknown {unknown}",
    )


def validate_outcome(outcome, requirement, evidence, executed_evidence=(), planned_runtime=()):
    """A reference is necessary for source claims; runtime deferrals stay explicit."""
    require(set(outcome["evidence_ids"]) <= set(evidence), "Unknown evidence ID")
    if outcome[OUTCOME] in {"satisfied", "contradicted"}:
        require(bool(outcome["evidence_ids"]), "Source claim needs observed evidence")
    if requirement["kind"] == "runtime":
        runtime_outcome(outcome, requirement, executed_evidence, planned_runtime)
    else:
        require(outcome[OUTCOME] != "deferred", "Required task evidence cannot be deferred")


def runtime_outcome(outcome, requirement, executed_evidence, planned_runtime):
    """Runtime acceptance needs this criterion's matching, current check assessment."""
    if outcome[OUTCOME] in {"deferred", "not_evaluated", "gap"}:
        return
    if outcome[OUTCOME] == "planned":
        require(
            requirement[IDENTIFIER] in planned_runtime,
            "Runtime planning needs an owned local check recipe",
        )
        return
    expected = "passed" if outcome[OUTCOME] == "satisfied" else "failed"
    matched = []
    for reference in outcome["evidence_ids"]:
        record = executed_evidence.get(reference) if isinstance(executed_evidence, dict) else None
        if record and requirement[IDENTIFIER] in record["criteria"]:
            matched.append(record["assessment"]["status"])
    require(expected in matched, "Runtime verification needs a matching current CheckResult")


def verdicts(payload, stage):
    """A missing input or unresolved required gap can never become an approval."""
    outcomes = {entry[OUTCOME] for entry in payload["coverage"]}
    if (
        payload["blocking_gaps"]
        or outcomes.intersection({"gap", "not_evaluated"})
        or payload.get("input_complete") is False
    ):
        require(payload[STATUS] == "BLOCKED", "Required gap must be BLOCKED")
    if "deferred" in outcomes:
        require(bool(payload["unverified"]), "Deferred verification needs concrete instructions")
    if payload[STATUS] == "IMPLEMENTED":
        require(
            not outcomes.intersection({"planned", "contradicted", "gap"}),
            "Implementation has unresolved criteria",
        )
    if payload[STATUS] == "APPROVE":
        require(not payload["findings"], "Approval cannot contain defects")
        require("contradicted" not in outcomes, "Approval contradicts requirements")
        if stage == "reviewer":
            require("planned" not in outcomes, "Final review cannot approve future work")
    if payload[STATUS] == "REQUEST_CHANGES":
        require(bool(payload["findings"]), "Changes requested without findings")


def validate_findings(findings, outcomes):
    """Every defect belongs to a known criterion; IDs must be unique."""
    unique(findings, "finding ID")
    for finding in findings:
        require(finding["criterion"] in outcomes, "Finding references unknown criterion")
