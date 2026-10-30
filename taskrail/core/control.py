"""Workflow controls shared by the CLI worker and local dashboard."""

STOP_FILE = "stop.request"
NOTE_LIMIT = 4000
NOTE_RULE = f"A continuation note is text of at most {NOTE_LIMIT} characters"


def check_stop(run):
    """Interrupt through the existing checkpoint and process cleanup path."""
    if (run / STOP_FILE).exists():
        raise KeyboardInterrupt


def clear_stop(run, resumed):
    """Clear the previous request only after resume integrity checks pass."""
    if resumed:
        (run / STOP_FILE).unlink(missing_ok=True)


def check_stage(stage, config):
    """Never enter a writer for an answer-only task, including imported plans."""
    if config.get("read_only") and stage == "implementer":
        raise ValueError("Answer-only tasks cannot enter implementation")
    if config.get("decompose") and stage == "implementer":
        raise ValueError("A task split is implemented by its separate task runs")


def check_plan(plan, config):
    """Reject changes suggested for a read-only request."""
    if config.get("read_only") and (plan["proposed_change_files"] or plan["steps"]):
        raise ValueError("Answer-only tasks require Decision: no change and no tasks")
    if config.get("phase") == "correction" and (
        plan.get("decision") == "split" or len(plan["steps"]) > 1
    ):
        raise ValueError("An integration correction requires one atomic task or no change")


def check_delta(delta, allowed, git_unchanged):
    """Source writes remain scoped even when remote execution is enabled."""
    forbidden = [name for name in delta if name not in allowed]
    if forbidden or not git_unchanged:
        raise ValueError(f"Scope violation or Git modification: {forbidden!r}")


def check_reads(reads, evidence):
    """History-only results can cite executor evidence without reading project files."""
    if not isinstance(reads, list) or not (reads or evidence):
        raise ValueError("Plan needs source reads or observed Git evidence")


def check_note(note):
    """An operator note for a continuation: bounded text, or None."""
    if note is None:
        return None
    if not isinstance(note, str) or "\x00" in note:
        raise ValueError(NOTE_RULE)
    if len(note) > NOTE_LIMIT:
        raise ValueError(NOTE_RULE)
    return note.strip() or None
