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
    """Legacy runs without a frozen limit never gain an automatic writer budget."""
    count = settings.get("max_repairs", 0)
    valid = isinstance(count, int) and not isinstance(count, bool)
    require(valid and 0 <= count <= 5, "Invalid correction budget")
    return count
