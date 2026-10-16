"""Join strict output shape, criterion coverage and attributed source evidence."""

from pathlib import Path

from countersign.application import declared_block, evidence, execution_evidence
from countersign.core import coverage, plan_contract, schema, source_claims
from countersign.core.files import atomic_json
from countersign.git.requests import output_directory


def validate(response, context):
    """Return a versioned result only after all independent validations pass."""
    payload = schema.decode(response, context["role"])
    atomic_json(context["folder"] / "response-object.json", payload)
    if declared_block.present(payload):
        payload = declared_block.stop_result(payload, context)
    coverage.validate_coverage(
        payload,
        context["requirements"],
        context["stage"],
        execution_evidence.claim_ids(context["run"], payload["evidence"]),
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
            ),
        )
        proofs.append(source_claims.validate_claim(claim, records))
    validate_role(payload, context)
    atomic_json(context["folder"] / "evidence-bindings.json", proofs)
    return payload


def approved_path(filename, roots):
    """Do not resolve guessed aliases or allow symlinks to expand source access."""
    path = Path(filename)
    schema.require(path.is_absolute() and path.resolve() == path, "Use canonical absolute paths")
    inside = any(root in path.parents for root in roots.values())
    schema.require(inside, f"Path outside declared roots or executor snapshots: {path}")


def validate_role(payload, context):
    """Cross-check stage-specific declarations against engine-owned inputs."""
    if context["role"] == "planner":
        plan_contract.validate_plan_steps(payload, context["requirements"])
        for filename in payload["files_read"] + payload["proposed_change_files"]:
            approved_path(filename, context["roots"])
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
