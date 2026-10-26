"""Durable stage allowances; continuation never silently resets consumption."""

import json

from taskrail.application.allowances import extend
from taskrail.core.files import atomic_json

ATTEMPTS = "attempts"

LIMITS = "limits"

STAGE = "stage"

TIMEOUT = "timeout"

DIRECTORY = "directory"
BUDGET_FILE = "budgets.json"
MODE = "mode"


class BudgetExceeded(ValueError):
    """Continuation requires an explicit allowance increase."""


def load(run):
    """Reservations survive process death before a result can be recorded."""
    path = run / BUDGET_FILE
    if path.exists():
        return json.loads(path.read_text())
    return {ATTEMPTS: {}, LIMITS: []}


def consumption(reservations, stage):
    """Use actual elapsed time, or the reserved timeout after an unclean crash."""
    selected = [entry for entry in reservations.values() if entry[STAGE] == stage]
    return {
        ATTEMPTS: len(selected),
        "seconds": sum(entry.get("elapsed", entry[TIMEOUT]) for entry in selected),
    }


def reserve(run, record, limits):
    """Persist a launch charge before spawning; never charge only after success."""
    ledger = load(run)
    limits = extend(ledger, record[STAGE], limits)
    used = consumption(ledger[ATTEMPTS], record[STAGE])
    allowance = remaining(used, limits)
    if not ledger[LIMITS] or ledger[LIMITS][-1] != limits:
        ledger[LIMITS].append(limits)
    ledger[ATTEMPTS][record[DIRECTORY]] = {
        DIRECTORY: record[DIRECTORY],
        STAGE: record[STAGE],
        MODE: record[MODE],
        TIMEOUT: allowance[TIMEOUT],
    }
    atomic_json(run / BUDGET_FILE, ledger)
    return allowance


def remaining(used, limits):
    """Distinguish attempt timeout, stage time and total launch count."""
    if used[ATTEMPTS] >= limits[ATTEMPTS]:
        raise BudgetExceeded("Stage attempt allowance exhausted")
    available = limits["seconds"] - used["seconds"]
    if available <= 0:
        raise BudgetExceeded("Stage time allowance exhausted")
    return {
        TIMEOUT: min(limits[TIMEOUT], available),
        "attempts_remaining": limits[ATTEMPTS] - used[ATTEMPTS] - 1,
        "stage_seconds_remaining": available,
    }


def settle(run, directory, outcome):
    """Replace pessimistic reservations with measured process duration."""
    ledger = load(run)
    entry = ledger[ATTEMPTS][directory]
    entry.update(elapsed=outcome["elapsed_seconds"], status=outcome["status"])
    atomic_json(run / BUDGET_FILE, ledger)
