"""When a run gets isolated worktrees without asking: the default `auto` isolation.

A code change gets them when every root is the top level of a Git repository with a
commit that is not already checked out on a Taskrail branch. Answers, designs,
delivery checks, the tasks and follow-ups of an isolated run and other roots work in
place.
"""

from pathlib import Path

from taskrail.git import process

BRANCH_PREFIX = "taskrail/"
REV_PARSE = "rev-parse"
ROOTS = "roots"


def wanted(config):
    """The task's choice, or by default a code change in repositories' top levels."""
    if config["isolation"] is not None:
        return config["isolation"]
    if config.get("read_only") or config.get("phase"):
        return False
    return all(map(isolatable, config[ROOTS].values()))


def isolatable(root):
    """A repository top level with a commit, not already checked out on a Taskrail branch."""
    head = process.invoke(root, [REV_PARSE, "--verify", "HEAD"])
    branch = process.invoke(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    on_branch = branch.stdout.strip().startswith(BRANCH_PREFIX)
    return top_level(root) and head.returncode == 0 and not on_branch


def top_level(root):
    """Whether a directory is the top level of a Git work tree."""
    top = process.invoke(root, [REV_PARSE, "--show-toplevel"])
    location = Path(top.stdout.strip()).resolve()
    return top.returncode == 0 and location == Path(root).resolve()
