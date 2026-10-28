"""Report all missing source evidence together, with safe alternatives to clipped JSON."""

from pathlib import Path

from taskrail.application import citation_delivery, source_views
from taskrail.core import citation_errors, prompt_texts, source_claims

ERROR_LIMIT = 5


def validate(claims, records, context):
    """Every citation must pass; bounded feedback repairs several gaps in one turn."""
    proofs = []
    errors = []
    views = {}
    for claim in claims:
        try:
            proofs.append(checked(claim, records, context))
        except citation_errors.MissingLines as error:
            delivered = context.get("deliver_lines") and citation_delivery.deliver(error, context)
            errors.append(delivered or guidance(claim, context, str(error), views))
        except ValueError as error:
            errors.append(guidance(claim, context, str(error), views))
    if errors:
        raise ValueError(feedback(errors))
    return proofs


def feedback(errors):
    """Cap the correction payload while disclosing any remaining failed claims."""
    omitted = len(errors) - ERROR_LIMIT
    suffix = prompt_texts.text("citation.remaining", count=omitted) if omitted > 0 else ""
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
    return prompt_texts.text("citation.source_view", error=error, **view)
