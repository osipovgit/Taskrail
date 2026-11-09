"""Every standalone task owns a linked Git worktree; child phases reuse its branch."""

from pathlib import Path

from taskrail.git import process

REV_PARSE = "rev-parse"


def wanted(config):
    """Standalone tasks always isolate; invalid roots fail preflight without fallback."""
    return not config.get("phase")


def isolatable(root):
    """A repository top level with a commit; branch names do not establish ownership."""
    if not Path(root).is_dir():
        return False
    head = process.invoke(root, [REV_PARSE, "--verify", "HEAD"])
    return top_level(root) and head.returncode == 0


def top_level(root):
    """Whether a directory is the top level of a Git work tree."""
    top = process.invoke(root, [REV_PARSE, "--show-toplevel"])
    location = Path(top.stdout.strip()).resolve()
    return top.returncode == 0 and location == Path(root).resolve()


def origins(entry):
    """Follow-ups retain canonical aliases for parent and original checkouts."""
    sources = {entry["source"], entry.get("original_source", entry["source"])}
    paths = map(Path, sorted(sources))
    return [path for path in paths if path.resolve() == path]
