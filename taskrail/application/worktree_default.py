"""When a run gets isolated worktrees without asking: the default `auto` isolation.

A code change gets them when every root is the top level of a Git repository with a
commit. Delivery phases inherit their authenticated parent's roots. Answers, designs,
follow-ups of isolated runs and other roots work in place.
"""

from pathlib import Path

from taskrail.git import process

REV_PARSE = "rev-parse"
ROOTS = "roots"


def wanted(config):
    """The task's choice, or by default a code change in repositories' top levels."""
    if config.get("phase"):
        return False
    if config["isolation"] is not None:
        return config["isolation"]
    if config.get("read_only"):
        return False
    return all(map(isolatable, config[ROOTS].values()))


def isolatable(root):
    """A repository top level with a commit; branch names do not establish ownership."""
    head = process.invoke(root, [REV_PARSE, "--verify", "HEAD"])
    return top_level(root) and head.returncode == 0


def top_level(root):
    """Whether a directory is the top level of a Git work tree."""
    top = process.invoke(root, [REV_PARSE, "--show-toplevel"])
    location = Path(top.stdout.strip()).resolve()
    return top.returncode == 0 and location == Path(root).resolve()
