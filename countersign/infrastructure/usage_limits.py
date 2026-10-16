"""Observe optional token thresholds; tool counts are metrics only."""


def exceeded(telemetry, token_budget):
    """Provider reporting may arrive after a token threshold has been crossed."""
    if token_budget is not None and telemetry.tokens["total"] >= token_budget:
        return "TOKEN_BUDGET_EXCEEDED"
    return "OK"
