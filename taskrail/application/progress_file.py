"""The implementer's progress file: what is done, what remains, what the review checks.

progress.md lives in the run directory, so a session that times out, overflows or is
interrupted leaves it behind and the next implementer session continues from it
instead of re-checking finished work. The implementer may write it besides its
allowed files; it is a note, never evidence, and the review still checks the result.
"""

from taskrail.core import prompt_texts
from taskrail.infrastructure.agent_sync import atomic_write

NAME = "progress.md"


def path(run):
    """Where the progress of a run is written."""
    return run / NAME


def prepare(run):
    """Write the template once; existing progress is continued, never replaced."""
    target = path(run)
    if not target.exists():
        atomic_write(target, prompt_texts.text("progress.template").encode())
    return target


def grant(access, run):
    """Let the implementer's profile read and write progress.md."""
    target = prepare(run)
    access["writable"] = [*access["writable"], target]
    access["readable"].append(target)


def instructions(run):
    """How the implementer keeps its progress."""
    return prompt_texts.text("progress.format", path=path(run))
