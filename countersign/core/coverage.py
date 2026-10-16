"""Validate requirement ownership and review decisions, independently of prose."""

from countersign.core.schema import require

OUTCOME = "outcome"
STATUS = "status"


def unique(entries, label):
    """Return indexed records while rejecting duplicate identifiers."""
    indexed = {entry["id"]: entry for entry in entries}
    require(len(indexed) == len(entries), f"Duplicate {label}")
    return indexed


def validate_coverage(payload, requirements, stage, executed_evidence=()):
    """Every supplied requirement must have a justified, stage-appropriate outcome."""
    outcomes = unique(payload["coverage"], "coverage ID")
    require(
        set(outcomes) == {entry["id"] for entry in requirements}, "Incomplete requirement coverage"
    )
    evidence = unique(payload["evidence"], "evidence ID")
    for entry in requirements:
        validate_outcome(outcomes[entry["id"]], entry, evidence, executed_evidence)
    validate_findings(payload.get("findings", []), outcomes)
    verdicts(payload, stage)


def validate_outcome(outcome, requirement, evidence, executed_evidence=()):
    """A reference is necessary for source claims; runtime deferrals stay explicit."""
    require(set(outcome["evidence_ids"]) <= set(evidence), "Unknown evidence ID")
    if outcome[OUTCOME] in {"satisfied", "contradicted"}:
        require(bool(outcome["evidence_ids"]), "Source claim needs observed evidence")
    if requirement["kind"] == "runtime":
        require(
            outcome[OUTCOME] in {"deferred", "not_evaluated"}
            or bool(set(outcome["evidence_ids"]) & set(executed_evidence)),
            "Runtime verification was not executed",
        )
    else:
        require(outcome[OUTCOME] != "deferred", "Required task evidence cannot be deferred")


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
