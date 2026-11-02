"""Canonical source paths and actionable diagnostics for result citations."""

from pathlib import Path

from taskrail.application import citation_review
from taskrail.core import prompt_texts, schema
from taskrail.git.requests import output_directory

EVIDENCE_FILES = "declared roots, verified source views, preimages or executor snapshots (not run artifacts such as changes.diff or recovery.md)"


def validate_paths(payload, context):
    """Report invalid citation paths together, tied to their requirement owners."""
    errors = []
    for claim in payload["evidence"]:
        roots = allowed_roots(claim, context)
        try:
            approved_path(claim["path"], roots, EVIDENCE_FILES)
        except ValueError as error:
            errors.append(path_feedback(payload, claim, error, context["stage"]))
    if errors:
        raise ValueError(citation_review.feedback(errors))


def path_feedback(payload, claim, error, stage):
    """Reviewers must not be told to use planner-only outcomes or fields."""
    owners = ", ".join(
        entry["id"] for entry in payload["coverage"] if claim["id"] in entry["evidence_ids"]
    )
    message = prompt_texts.diagnostic("validation.evidence_path", owners=owners, error=error)
    if stage == "planner":
        message = f"{message} {prompt_texts.diagnostic('validation.plan_evidence_path')}"
    return message


def allowed_roots(claim, context):
    """Run artifacts remain excluded even if a broad project root contains the run."""
    if context["run"] in Path(claim["path"]).parents:
        return snapshots(context["run"])
    return context["roots"]


def snapshots(run):
    """The run-owned directories that may contain independently recorded evidence."""
    return dict(
        git_evidence=output_directory(run),
        ssh_evidence=run / "00-input/ssh",
        local_evidence=run / "00-input/local",
        check_evidence=run / "00-input/checks",
        source_views=run / "00-input/source-views",
        preimages=run / "00-input/preimages",
    )


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
