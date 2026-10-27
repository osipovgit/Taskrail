"""Totals across all runs: outcomes, time, tokens, and failures by model and stage."""

from collections import Counter

from taskrail.web.run_files import contained, read_json

SUCCESS = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED", "TASKS_READY"))
STAGE_OK = frozenset(
    ("RESULT_VALID", "CHECK_COMPLETED", "ACTION_REQUEST", "GIT_REQUEST", "RUNNING")
)
RECOVERY_MODES = frozenset(("access-recovery", "research-recovery"))
DEFAULT_MODEL = "opencode default"
ELAPSED = "elapsed_seconds"
TOKENS = "tokens"
CORRECTIONS = "result_corrections"


def analytics(base):
    """Run, model and stage totals of every readable run under base."""
    states = [state for state in map(run_state, run_dirs(base)) if state]
    return dict(
        runs=run_totals(states),
        models=grouped(states, lambda record: record.get("model") or DEFAULT_MODEL),
        stages=grouped(states, lambda record: record.get("stage", "unknown")),
    )


def run_dirs(base):
    """Run directories; hidden storage such as .submissions and .trash is skipped."""
    if not base.is_dir():
        return []
    visible = [path for path in base.iterdir() if not path.name.startswith(".")]
    return [path for path in visible if path.is_dir()]


def run_state(path):
    """A readable run index, or None."""
    if path.is_symlink():
        return None
    try:
        state = read_json(contained(path, "run.json"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def run_totals(states):
    """Outcomes, success rate, recorded time and tokens, and continuations."""
    statuses = Counter(state.get("status") for state in states)
    succeeded = sum(statuses[status] for status in SUCCESS)
    metrics = [state.get("metrics") or {} for state in states]
    return dict(
        count=len(states),
        succeeded=succeeded,
        success_rate=round(succeeded / len(states), 3) if states else None,
        statuses=dict(statuses.most_common()),
        elapsed_seconds=round(sum(metric.get(ELAPSED, 0) for metric in metrics), 1),
        tokens=sum(total_tokens(metric.get(TOKENS)) for metric in metrics),
        continuations=sum(len(state.get("continuations", [])) for state in states),
    )


def grouped(states, key):
    """Attempts, failures, repairs, recoveries, time and tokens per group of stage records."""
    totals = {}
    for state in states:
        for record in state.get("stages", []):
            empty = dict(attempts=0, failed=0, format_repairs=0, recoveries=0, tokens=0)
            empty.update(first_try=0, first_try_measured=0)
            entry = totals.setdefault(key(record), dict(empty, elapsed_seconds=0))
            add(entry, record)
    return totals


def add(entry, record):
    """Count one stage record.

    A model attempt that recorded its same-session corrections counts toward the
    first-try share: valid without any correction.
    """
    mode = record.get("mode")
    accepted = record.get("status") in STAGE_OK
    measured = mode == "model" and CORRECTIONS in record
    entry["attempts"] += 1
    entry["failed"] += not accepted
    entry["first_try_measured"] += measured
    entry["first_try"] += measured and accepted and not record[CORRECTIONS]
    entry["format_repairs"] += mode == "format-repair"
    entry["recoveries"] += mode in RECOVERY_MODES
    entry[TOKENS] += total_tokens(record.get(TOKENS))
    elapsed = entry[ELAPSED] + record.get(ELAPSED, 0)
    entry[ELAPSED] = round(elapsed, 1)


def total_tokens(usage):
    """Reported total tokens; missing usage counts as none reported."""
    return (usage or {}).get("total", 0)
