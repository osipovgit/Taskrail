"""The review file a reviewer writes: its template, its instructions and its result.

review.md lives in the run directory, so an interrupted session leaves it behind and
the next attempt of the same review continues it. A review that starts after another
stage gets a fresh template. The reviewer may write only this file; the server reads
it, derives the review result and names every problem by line.
"""

from taskrail.core import prompt_texts
from taskrail.infrastructure.agent_sync import atomic_write

NAME = "review.md"


def path(run):
    """Where the review of a run is written."""
    return run / NAME


def prepare(run, requirements, fresh=False):
    """Write the template for a new review; a review in progress is continued."""
    target = path(run)
    if fresh or not target.exists():
        numbers = range(1, len(requirements) + 1)
        lines = "\n".join(f"- R{number}: <outcome>" for number in numbers)
        atomic_write(target, prompt_texts.text("review.template", requirements=lines).encode())
    return target


def grant(access, run, requirements):
    """Let the reviewer's profile read and write review.md, and only that file."""
    target = prepare(run, requirements)
    access["writable"] = [*access["writable"], target]
    access["readable"].append(target)


def instructions(run, stage):
    """The review format and the stage's own rules."""
    rules = prompt_texts.text("review.format", path=path(run))
    return "{} {}".format(rules, prompt_texts.text(f"review.{stage}"))
