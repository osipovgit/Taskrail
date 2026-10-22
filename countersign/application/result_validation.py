"""Join strict output shape, criterion coverage and attributed source evidence."""

from pathlib import Path

from countersign.application import (
    check_planning,
    decision_adapter,
    declared_block,
    evidence,
    execution_evidence,
    plan_file,
    plan_result,
)
from countersign.core import (
    coverage,
    plan_contract,
    schema,
    source_claims,
)
from countersign.core.files import atomic_json
from countersign.git.requests import output_directory

EVIDENCE_FILES = "declared roots or executor snapshots (cite the source file itself, not run artifacts such as changes.diff or recovery.md)"
PLAN_FILES = "declared roots (files_read and proposed_change_files name project files; cite executor snapshots only in evidence)"


def validate(response, context):
    """Return a versioned result only after all independent validations pass.

    A planner's problems name requirements by their plan labels.
    """
    if context["stage"] != plan_result.PLANNER:
        return checked(decision_adapter.stage_decision(response, context), context)
    try:
        return checked(plan_result.stage_result(context), context)
    except ValueError as error:
        raise ValueError(plan_file.labelled(str(error), context["requirements"])) from error


def checked(payload, context):
    """Coverage, evidence and role checks of a decoded result."""
    atomic_json(context["folder"] / "response-object.json", payload)
    if declared_block.present(payload):
        payload = declared_block.stop_result(payload, context)
    coverage.validate_coverage(
        payload,
        context["requirements"],
        context["stage"],
        execution_evidence.claim_ids(context["run"], payload["evidence"]),
        check_planning.criteria(payload, context),
    )
    run = context["run"]
    records = [record for record in evidence.validation_records(run) if evidence.current(record)]
    proofs = []
    for claim in payload["evidence"]:
        approved_path(
            claim["path"],
            dict(
                context["roots"],
                git_evidence=output_directory(run),
                ssh_evidence=run / "00-input/ssh",
                local_evidence=run / "00-input/local",
                check_evidence=run / "00-input/checks",
            ),
            EVIDENCE_FILES,
        )
        proofs.append(source_claims.validate_claim(claim, records))
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
    if context["role"] == "planner":
        plan_contract.validate_plan_steps(payload, context["requirements"])
        for filename in payload["files_read"] + payload["proposed_change_files"]:
            approved_path(filename, context["roots"], PLAN_FILES)
        observed = {
            record["input"]["filePath"]
            for record in evidence.validation_records(context["run"])
            if evidence.current(record)
        }
        schema.require(set(payload["files_read"]) <= observed, "Unobserved files_read claim")
    elif context["role"] == "implementer":
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
    observed = {claim["path"] for claim in payload["evidence"]}
    for finding in payload["findings"]:
        schema.require(finding["file"] in observed, "Finding needs observed source evidence")
