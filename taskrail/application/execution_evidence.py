"""Bind runtime claims to completed, server-recorded checks."""

from taskrail.application import check_results


def claim_ids(run, claims):
    """Only current, criterion-bound checks can substantiate runtime acceptance."""
    trusted = check_results.trusted(run)
    bound = {}
    for claim in claims:
        recorded = trusted.get(claim["path"])
        if recorded:
            bound[claim["id"]] = recorded
    return bound
