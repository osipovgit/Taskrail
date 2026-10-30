"""Live approval inheritance requires the server's exact parent-to-child record."""

from taskrail.core import approval_marks, delivery_record, input_header, owned_paths
from taskrail.core.schema import require

PHASES = frozenset(("integration", "validation", "server", "correction"))
ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError)
INVALID = object()


def status(run, phase):
    """(durable personal grant, denial); any ancestor denial wins over copied flags."""
    granted = False
    visited = set()
    while run is not None:
        if run is INVALID or run in visited or approval_marks.revoked(run):
            return False, True
        visited.add(run)
        granted = granted or approval_marks.granted(run) or recorded(run)
        run = parent(run, strict=True)
        if run is None and phase in {*PHASES, "task"}:
            return False, True
        phase = None
    return granted, False


def parent(run, strict=False):
    """Malformed, absent or guessed lineage cannot inherit another run's authority."""
    try:
        return linked(run)
    except ERRORS:
        return INVALID if strict else None


def linked(run):
    """Task text supplies a claim; only the server-owned epic record authenticates it."""
    run = owned_paths.child(run.parent, run.name)
    task = owned_paths.child(run, "00-input/task.md")
    if not task.exists() and not owned_paths.child(run, "run.json").exists():
        return None
    claim = reference(input_header.parse(task.read_text(encoding="utf-8")))
    if claim is None:
        return None
    owner = owned_paths.child(run.parent, claim[0])
    require(owner != run, "Invalid approval parent")
    names = members(delivery_record.read(owner), claim)
    require(run.name in names, "Approval parent no longer links this worker")
    return owner


def members(record, claim):
    """The exact assigned slot must contain this worker, not merely any parent slot."""
    if claim[2] == "task":
        return delivery_record.attempts(record, claim[1])
    return phases(record, claim[1])


def reference(metadata):
    """Only task assignments and delivery phases can claim a family relationship."""
    kind = metadata.get("phase")
    if kind == "task":
        contract = metadata.get("assigned_contract", {})
        name, slot = contract.get("parent_run"), contract.get("task_id")
    elif kind in PHASES:
        name, slot = metadata.get("check_parent"), kind
    else:
        return None
    valid_name = isinstance(name, str) and bool(delivery_record.RUN_NAME.fullmatch(name))
    require(valid_name, "Invalid approval parent ID")
    require(isinstance(slot, str) and bool(slot), "Invalid approval assignment")
    return name, slot, kind


def phases(record, slot):
    """Recorded phase attempts remain authenticated after a newer attempt starts."""
    names = list(record.get("phase_attempts", {}).get(slot, []))
    for phase in (record.get("phases", {}), *record.get("phase_history", [])):
        name = phase.get(slot)
        if name is not None:
            names.append(name)
    return names


def recorded(run):
    """Existing family grants remain effective when upgrading from in-memory workers."""
    try:
        return delivery_record.read(run).get("auto_approve") is True
    except ERRORS:
        return False
