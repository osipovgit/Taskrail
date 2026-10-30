"""The implementer's progress file: what is done, what remains, what the review checks.

progress.md lives in the run directory, so a session that times out, overflows or is
interrupted leaves it behind and the next implementer session continues from it
instead of re-checking finished work. The implementer may write it besides its
allowed files; it is a note, never evidence, and the review still checks the result.
"""

from taskrail.application import progress_archive
from taskrail.core import prompt_texts
from taskrail.infrastructure.agent_sync import atomic_write

NAME = "progress.md"


def path(run):
    """Where the progress of a run is written."""
    return run / NAME


def prepare(run):
    """Keep a bounded working note and preserve every oversized version verbatim."""
    target = path(run)
    if not target.exists():
        atomic_write(target, prompt_texts.text("progress.template").encode())
    progress_archive.bound(run, target)
    return target


def grant(access, run):
    """Let the implementer's profile read and write progress.md."""
    target = prepare(run)
    access["writable"] = [*access["writable"], target]
    access["readable"].append(target)
    access["readable"].extend(progress_archive.paths(run))


def overflow(run, role):
    """Prepare a fresh profile before granting exact access to a newly archived note."""
    target = path(run)
    if role != "implementer" or not target.exists():
        return None
    if target.stat().st_size <= progress_archive.MAX_BYTES:
        return None
    return dict(
        status="CONTEXT_EXCEEDED",
        final_text="",
        errors=["Progress note exceeds its handoff limit; a bounded fresh session is required"],
        completed=False,
        tokens={},
        elapsed_seconds=0,
        usage_complete=False,
    )


def instructions(run):
    """How the implementer keeps its progress."""
    return prompt_texts.text("progress.format", path=path(run))
