"""Canonical source paths and actionable diagnostics for result citations."""

from pathlib import Path

from taskrail.application import (
    citation_review,
    evidence_scope,
    plan_review_evidence,
)
from taskrail.core import prompt_texts, schema

EVIDENCE_FILES = "declared roots, verified source views, preimages or executor snapshots (not run artifacts such as changes.diff or recovery.md)"


def validate_paths(payload, context):
    """Report invalid citation paths together, tied to their requirement owners."""
    evidence_scope.verify_dependencies(context, payload["evidence"])
    errors = []
    for claim in payload["evidence"]:
        try:
            validate_claim(claim, payload, context)
        except ValueError as error:
            errors.append(path_feedback(payload, claim, error, context["stage"]))
    if errors:
        raise ValueError(citation_review.feedback(errors))


def validate_claim(claim, payload, context):
    """Accept the current stage's authenticated document or an in-scope source path."""
    if claim["path"] == context.get("submission_path"):
        return
    if not plan_review_evidence.accepts(claim, payload, context):
        approved_path(claim["path"], allowed_roots(claim, context), EVIDENCE_FILES)


def path_feedback(payload, claim, error, stage):
    """Reviewers must not be told to use planner-only outcomes or fields."""
    rows = [*payload["coverage"], *payload.get("finding_checks", ())]
    matching = (entry for entry in rows if claim["id"] in entry["evidence_ids"])
    owners = ", ".join(entry["id"] for entry in matching)
    if stage == "plan-reviewer":
        return f"{owners}: {error}. {prompt_texts.diagnostic('validation.plan_review_path')}"
    message = prompt_texts.diagnostic("validation.evidence_path", owners=owners, error=error)
    if stage == "planner":
        message = f"{message} {prompt_texts.diagnostic('validation.plan_evidence_path')}"
    return message


def allowed_roots(claim, context):
    """Run artifacts remain excluded even if a broad project root contains the run."""
    path = Path(claim["path"])
    run = context["run"]
    if run not in path.parents:
        return context["roots"]
    return dict(
        evidence_scope.roots(run, path, context["roots"]),
        source_views=context["run"] / "00-input/source-views",
    )


def approved_path(filename, roots, scope="declared roots or executor snapshots"):
    """Do not resolve guessed aliases or allow symlinks to expand source access."""
    path = Path(filename)
    canonical = path.is_absolute() and path.resolve() == path
    schema.require(canonical, f"Use canonical absolute paths, not {filename}{example(path, roots)}")
    inside = any(root in path.parents for root in roots.values())
    schema.require(
        inside,
        prompt_texts.diagnostic(
            "validation.path_scope",
            scope=scope,
            path=path,
            roots=", ".join(map(str, roots.values())),
        ),
    )


def example(path, roots):
    """The absolute form of a relative path that exists in a declared root."""
    if path.is_absolute():
        return ""
    for root in roots.values():
        candidate = root / path
        if candidate.exists():
            return f" (for example {candidate})"
    return ""
