"""Apply explicit operator grants without resetting past consumption."""


def extend(ledger, stage, limits):
    """Use the greater configured or persisted allowance for each dimension."""
    adjusted = dict(limits)
    floors = ledger.get("extensions", {}).get(stage, {})
    for name, amount in floors.items():
        if name not in adjusted:
            continue
        adjusted[name] = max(adjusted[name], amount)
    return adjusted
