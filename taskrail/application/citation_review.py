"""Report all missing source evidence together, with safe alternatives to clipped JSON."""

from pathlib import Path

from taskrail.application import source_views
from taskrail.core import source_claims

ERROR_LIMIT = 5


def validate(claims, records, context):
    """Every citation must pass; bounded feedback repairs several gaps in one turn."""
    proofs = []
    errors = []
    views = {}
    for claim in claims:
        try:
            proofs.append(checked(claim, records, context))
        except ValueError as error:
            errors.append(guidance(claim, context, str(error), views))
    if errors:
        raise ValueError(feedback(errors))
    return proofs


def feedback(errors):
    """Cap the correction payload while disclosing any remaining failed claims."""
    omitted = len(errors) - ERROR_LIMIT
    suffix = f"\n{omitted} further invalid citations remain." if omitted > 0 else ""
    return "\n".join(errors[:ERROR_LIMIT]) + suffix


def checked(claim, records, context):
    """A derived view proves only its observed lines and its unchanged original source."""
    run = context["run"]
    path = Path(claim["path"])
    derived = source_views.directory(run) in path.parents
    provenance = source_views.validate(run, path, context["roots"]) if derived else None
    proof = source_claims.validate_claim(claim, records)
    if provenance:
        proof["source_view"] = provenance
    return proof


def guidance(claim, context, error, views):
    """A clipped raw JSON line cannot be repaired by repeating the same read."""
    path = Path(claim["path"])
    if path not in views:
        views[path] = source_views.prepare(context["run"], path, context["roots"])
    view = views[path]
    if view is None:
        return error
    return (
        f"{error}\nThe raw JSON has oversized lines. A lossless formatted source view is "
        f"available at {view['path']} ({view['lines']} lines). Search that view and read only "
        "relevant windows of at most 200 lines, then cite those view ranges in the plan or "
        "result. Do not repeat the clipped raw read or claim the whole report was observed."
    )
