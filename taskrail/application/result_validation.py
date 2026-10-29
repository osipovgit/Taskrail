"""Join strict output shape, criterion coverage and attributed source evidence."""

from pathlib import Path

from taskrail.application import (
    check_planning,
    citation_review,
    declared_block,
    evidence,
    execution_evidence,
    plan_file,
    plan_result,
    review_result,
)
from taskrail.application.implementer_result import stage_result as implementation
from taskrail.core import (
    coverage,
    plan_contract,
    schema,
)
from taskrail.core.files import atomic_json
from taskrail.git.requests import output_directory

EVIDENCE_FILES = "declared roots, verified source views, preimages or executor snapshots (not run artifacts such as changes.diff or recovery.md)"
PLAN_FILES = "declared roots (files_read and proposed_change_files name project files; cite executor snapshots only in evidence)"
EVIDENCE = "evidence"
IMPLEMENTER = "implementer"
ROLE = "role"


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
    if context["stage"] == plan_result.PLANNER:
        return plan_result.stage_result(context)
    if context[ROLE] == IMPLEMENTER:
        return implementation(response, context)
    return review_result.stage_result(context)


def checked(payload, context):
    """Coverage, evidence and role checks of a decoded result."""
    atomic_json(context["folder"] / "response-object.json", payload)
    run = context["run"]
    records = [record for record in evidence.validation_records(run) if evidence.current(record)]
    if context["stage"] == plan_result.PLANNER and declared_block.present(payload):
        payload = declared_block.stop_result(payload, context)
    payload = review_result.settled(payload, records, context)
    if context[ROLE] != IMPLEMENTER:
        coverage.validate_coverage(
            payload,
            context["requirements"],
            context["stage"],
            execution_evidence.claim_ids(context["run"], payload[EVIDENCE]),
            check_planning.criteria(payload, context),
        )
    for claim in payload[EVIDENCE]:
        approved_path(
            claim["path"],
            dict(
                context["roots"],
                git_evidence=output_directory(run),
                ssh_evidence=run / "00-input/ssh",
                local_evidence=run / "00-input/local",
                check_evidence=run / "00-input/checks",
                source_views=run / "00-input/source-views",
                preimages=run / "00-input/preimages",
            ),
            EVIDENCE_FILES,
        )
    proofs = citation_review.validate(payload[EVIDENCE], records, context)
    validate_role(payload, context)
    atomic_json(context["folder"] / "evidence-bindings.json", proofs)
    return payload


def approved_path(filename, roots, scope="declared roots or executor snapshots"):
    """Do not resolve guessed aliases or allow symlinks to expand source access."""
    path = Path(filename)
    canonical = path.is_absolute() and path.resolve() == path
    schema.require(canonical, f"Use canonical absolute paths, not {filename}{example(path, roots)}")
    inside = any(root in path.parents for root in roots.values())
    schema.require(inside, f"Path outside {scope}: {path}")


def example(path, roots):
    """The absolute form of a relative path that exists in a declared root."""
    if path.is_absolute():
        return ""
    for root in roots.values():
        candidate = root / path
        if candidate.exists():
            return f" (for example {candidate})"
    return ""


def validate_role(payload, context):
    """Cross-check stage-specific declarations against engine-owned inputs."""
    if context[ROLE] == "planner":
        plan_contract.validate_plan_steps(payload, context["requirements"])
        for filename in payload["files_read"] + payload["proposed_change_files"]:
            approved_path(filename, context["roots"], PLAN_FILES)
        observed = {
            record["input"]["filePath"]
            for record in evidence.validation_records(context["run"])
            if evidence.current(record)
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
            all(entry["outcome"] in {"satisfied", "deferred"} for entry in payload["coverage"]),
            "No-change approval cannot contain future work",
        )
    observed = {claim["path"] for claim in payload[EVIDENCE]}
    for finding in payload["findings"]:
        schema.require(finding["file"] in observed, "Finding needs observed source evidence")
