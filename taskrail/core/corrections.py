"""Durable correction lineage shared by execution, delivery scheduling and history."""

from taskrail.core import delivery_record
from taskrail.core.schema import require

PHASE = "correction"
KEY = "corrections"


def records(epic):
    """Every correction names its own run and the rejected review it addresses."""
    entries = epic.get(KEY, [])
    require(isinstance(entries, list), "Invalid correction history")
    for entry in entries:
        require(
            isinstance(entry, dict) and set(entry) == {"run", "review"}, "Invalid correction link"
        )
        require(
            all(
                isinstance(name, str) and delivery_record.RUN_NAME.fullmatch(name)
                for name in entry.values()
            ),
            "Invalid correction run ID",
        )
    names = [record["run"] for record in entries]
    require(len(names) == len(set(names)), "Duplicate correction run")
    return entries


def limit(settings):
    """Validate the frozen automatic writer budget."""
    return setting(settings, "max_integration_corrections", 0)


def setting(options, key, default, minimum=0):
    """Reject invalid limits explicitly instead of silently changing them."""
    amount = options.get(key, default)
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < minimum:
        raise ValueError(f"{key} must be an integer of at least {minimum}")
    return amount
