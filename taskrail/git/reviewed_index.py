"""Recognize settled commit/index receipts when an operator restarts a reviewed task."""

from taskrail.git import history_outcome, index_ownership, process, requests, staging_receipt


def completed(run, root, paths):
    """Reuse an existing own commit only while its HEAD and reviewed contents still match."""
    if staged_paths(root):
        return None
    head = history_outcome.head(root)
    for receipt in own_receipts(run, root):
        if receipt.get("head") == head:
            return head if committed_files(root, paths, head) else None
    return None


def own_receipts(run, root):
    """Completed controlled history writes in this repository, newest first."""
    for entry in reversed(requests.history(run)):
        belongs = entry.get("repository") == str(root)
        if belongs and entry["status"] == "SUCCEEDED":
            yield entry.get("source_baseline") or {}


def committed_files(root, paths, head):
    """The actual tree must contain the current bytes and executable modes of every file."""
    for name in paths:
        listing = process.checked(root, ["ls-tree", "-z", head, "--", name])
        identity = history_outcome.tree_entry(listing)
        if staging_receipt.working_identity(root, identity) != index_ownership.file_digest(
            root / name
        ):
            return False
    return True


def staged(run, root, paths):
    """A previously staged index is reusable only with its receipt and unchanged source."""
    names = staged_paths(root)
    wanted = [root / name for name in paths]
    if not names or not set(names) <= set(wanted):
        return False
    owned = index_ownership.owned(requests.history(run), root)
    if not index_ownership.belongs(root, names, owned):
        return False
    for name, identity in index_ownership.entries(root, wanted).items():
        if staging_receipt.working_identity(root, identity) != index_ownership.file_digest(
            root / name
        ):
            return False
    return True


def staged_paths(root):
    """Exact index paths; neither textconv nor external diff programs are enabled."""
    listing = process.checked(root, ["diff", "--cached", "--name-only", "--no-renames", "-z"])
    return [root / name for name in listing.split("\x00") if name]
