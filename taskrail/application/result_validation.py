"""Join strict output shape, criterion coverage and attributed source evidence."""

from taskrail.application import (
    check_planning,
    citation_review,
    declared_block,
    evidence_delivery,
    execution_evidence,
    plan_file,
    plan_result,
    review_result,
)
from taskrail.application.implementer_result import stage_result as implementation
from taskrail.application.result_paths import approved_path as approved_path
from taskrail.application.result_paths import validate_paths
from taskrail.core import (
    coverage,
    plan_contract,
    schema,
)
from taskrail.core.files import atomic_json

PLAN_FILES = "declared roots (files_read and proposed_change_files name project files; cite executor snapshots only in evidence)"
EVIDENCE = "evidence"
IMPLEMENTER = "implementer"
ROLE = "role"
STAGE = "stage"


def validate(response, context):
    """Return a versioned result only after all independent validations pass.

    Problems name requirements by the R<n> labels of the request.
    """
    try:
        return checked(decoded(response, context), context)
    except ValueError as error:
        message = plan_file.labelled(str(error), context["requirements"])
        if message == str(error):
            raise
        raise ValueError(message) from error


def decoded(response, context):
    """The planner's result comes from plan.md, a reviewer's from review.md and the
    implementer's from its final DONE or BLOCKED."""
    if context[STAGE] == plan_result.PLANNER:
        return plan_result.stage_result(context)
    if context[ROLE] == IMPLEMENTER:
        return implementation(response, context)
    return review_result.stage_result(context)


def checked(payload, context):
    """Coverage, evidence and role checks of a decoded result."""
    atomic_json(context["folder"] / "response-object.json", payload)
    records = evidence_delivery.session_records(context)
    if context[STAGE] == plan_result.PLANNER and declared_block.present(payload):
        payload = declared_block.stop_result(payload, context)
    if context[STAGE] == plan_result.PLANNER:
        validate_planner(payload, context)
    else:
        validate_paths(payload, context)
        payload = review_result.settled(payload, records, context)
        validate_coverage(payload, context)
        validate_role(payload, context)
    proofs = citation_review.validate(payload[EVIDENCE], records, context)
    atomic_json(context["folder"] / "evidence-bindings.json", proofs)
    return payload


def validate_planner(payload, context):
    """Report independent structural defects together before reading cited source bytes."""
    problems = []
    for validate in (validate_paths, validate_coverage, validate_role):
        try:
            validate(payload, context)
        except ValueError as error:
            problems.append(str(error))
    if problems:
        raise ValueError("\n".join(problems))


def validate_coverage(payload, context):
    """Requirement ownership is checked separately from source-path authorization."""
    if context[ROLE] != IMPLEMENTER:
        coverage.validate_coverage(
            payload,
            context["requirements"],
            context[STAGE],
            execution_evidence.claim_ids(context["run"], payload[EVIDENCE]),
            check_planning.criteria(payload, context),
        )


def validate_role(payload, context):
    """Cross-check stage-specific declarations against engine-owned inputs."""
    if context[ROLE] == "planner":
        plan_contract.validate_plan_steps(payload, context["requirements"])
        for filename in payload["files_read"] + payload["proposed_change_files"]:
            approved_path(filename, context["roots"], PLAN_FILES)
        observed = {
            record["input"]["filePath"] for record in evidence_delivery.session_records(context)
        }
        schema.require(set(payload["files_read"]) <= observed, "Unobserved files_read claim")
    elif context[ROLE] == IMPLEMENTER:
        plan_contract.validate_completion(payload, context["plan"], context["changed"])
    else:
        validate_review(payload, context["plan"])


def validate_review(payload, plan):
    """No-change approval needs completed static evidence, not future actions."""
    if payload["status"] == "APPROVE" and not plan["proposed_change_files"]:
        schema.require(
            all(
                entry["outcome"] in {"satisfied", "deferred", "not_applicable"}
                for entry in payload["coverage"]
            ),
            "No-change approval cannot contain future work",
        )
    observed = {claim["path"] for claim in payload[EVIDENCE]}
    for finding in payload["findings"]:
        schema.require(finding["file"] in observed, "Finding needs observed source evidence")
