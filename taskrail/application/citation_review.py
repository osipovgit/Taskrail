"""Report all missing source evidence together, with safe alternatives to clipped JSON."""

from pathlib import Path

from taskrail.application import citation_delivery, executor_streams, source_views
from taskrail.core import citation_errors, prompt_texts, source_claims

ERROR_LIMIT = 5


def validate(claims, records, context):
    """Every citation must pass; bounded feedback repairs several gaps in one turn."""
    proofs = []
    errors = {}
    views = {}
    for claim in pending(claims, errors):
        try:
            proofs.append(checked(claim, records, context))
        except citation_errors.MissingLines as error:
            delivered = delivery(error, context, len(errors))
            errors[window(claim)] = delivered or guidance(
                claim,
                context,
                str(error),
                views,
            )
        except ValueError as error:
            errors[window(claim)] = guidance(claim, context, str(error), views)
    if errors:
        raise ValueError(feedback(errors.values()))
    return proofs


def window(claim):
    """One source range may support multiple independently checked requirements."""
    return claim["path"], claim["line_start"], claim["line_end"]


def pending(claims, errors):
    """A repeated failing window shares feedback; successful claims keep individual proofs."""
    for claim in claims:
        if window(claim) not in errors:
            yield claim


def delivery(error, context, preceding):
    """Only missing citations inside the feedback limit may prepare source delivery."""
    if context.get("deliver_lines") and preceding < ERROR_LIMIT:
        return citation_delivery.deliver(error, context)
    return None


def feedback(errors):
    """Every failed claim is included in the pageable correction."""
    return "\n".join(errors)


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
        streams = executor_streams.guidance(context["run"], path)
        return f"{error}\n{streams}" if streams else error
    return prompt_texts.text("citation.source_view", error=error, **view)
