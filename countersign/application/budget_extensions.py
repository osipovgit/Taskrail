"""Explicit user-authorized continuation grants, without erasing consumption."""

from countersign.application import budgets
from countersign.core.files import atomic_json

ATTEMPTS = "attempts"


def grant(run, stage, config):
    """Add two launches and one attempt timeout to this stage."""
    ledger = budgets.load(run)
    used = budgets.consumption(ledger[ATTEMPTS], stage)
    previous = ledger.setdefault("extensions", {}).get(stage, {})
    previous.setdefault(ATTEMPTS, config["stage_attempts"])
    extension = {
        ATTEMPTS: max(used[ATTEMPTS], previous[ATTEMPTS]) + 2,
        "seconds": max(used["seconds"], previous.get("seconds", config["stage_seconds"]))
        + config["timeout"],
    }
    ledger["extensions"][stage] = extension
    ledger.setdefault("grants", []).append({"stage": stage, "limits": extension})
    atomic_json(run / budgets.BUDGET_FILE, ledger)
