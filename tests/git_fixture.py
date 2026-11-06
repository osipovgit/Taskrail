"""Real disposable repositories for workflows that always create linked worktrees."""

from taskrail.git import process


def repository(root):
    """Commit fixture setup; call before introducing intentionally pending user changes."""
    metadata = root / ".git"
    if metadata.is_dir() and not (metadata / "config").exists():
        (metadata / "HEAD").unlink()
        metadata.rmdir()
    process.checked(root, ["init", "-b", "main"])
    process.checked(root, ["config", "user.name", "Fixture"])
    process.checked(root, ["config", "user.email", "fixture@example.invalid"])
    process.checked(root, ["add", "."])
    pending = process.checked(root, ["diff", "--cached", "--name-only"])
    if pending or process.invoke(root, ["rev-parse", "--verify", "HEAD"]).returncode:
        process.checked(root, ["commit", "--allow-empty", "-m", "Fixture baseline"])
    return process
