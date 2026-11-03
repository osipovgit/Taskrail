"""Agent-requested source recovery preserves staged content, commits and earlier user edits."""

import subprocess
from pathlib import Path

from taskrail.core.files import digest
from taskrail.core.schema import require
from taskrail.git import index_ownership, process, source_scope, staging_receipt

ERROR = "Git restore did not preserve its approved index and source identity"


def prepare(root, argv, context, staged):
    """Restore exact authorized regular files to index entries, never a whole checkout."""
    repo = context["repository"]
    paths = [root / name for name in argv[3:]]
    source_scope.check_paths(paths, context["allowed"])
    source_scope.original_clean(repo, paths, context["baseline"])
    selected = [path for path in staged if path in paths]
    require(
        index_ownership.belongs(repo, selected, context["owned"]),
        "Restore cannot overwrite a file with user-owned staged changes; repair it directly",
    )
    require(
        all(map(regular_entry, index_ownership.entries(repo, paths).values())),
        "Restore requires tracked, unconflicted regular files; repair other files directly",
    )
    context["affected_paths"] = paths
    return argv


def regular_entry(identity):
    """No deleted entry, conflict, symlink or gitlink may become a restore target."""
    return (
        identity is not None
        and identity.startswith(("100644:", "100755:"))
        and identity.endswith(":0")
    )


def index_digest(repo):
    """Index content identity excludes Git's stat-cache refreshes."""
    return digest(process.checked(repo, ["ls-files", "--stage", "-z"]).encode())


def fingerprint(repo, root, argv):
    """Pin source and target content, including unrelated staged entries, before restore."""
    paths = [root / name for name in argv[3:]]
    return dict(
        files={str(path): index_ownership.file_digest(path) for path in paths},
        target=index_ownership.entries(repo, paths),
        index=index_digest(repo),
    )


def record(entry):
    """A successful subprocess is insufficient when concurrent Git changes are possible."""
    command = entry["request"]["argv"][0]
    if entry["status"] != "SUCCEEDED" or command != "restore":
        return
    try:
        verify(Path(entry["repository"]), entry)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        entry.update(status="UNKNOWN", stderr=f"Cannot verify restored source: {error}")


def verify(repo, entry):
    """Compare restored bytes/mode to pinned blobs; recheck index and HEAD afterwards."""
    expected = entry["fingerprint"]
    require(index_digest(repo) == expected["index"], ERROR)
    for name, identity in expected["target"].items():
        restored = index_ownership.file_digest(Path(name))
        require(restored == staging_receipt.working_identity(repo, identity), ERROR)
    require(index_digest(repo) == expected["index"], ERROR)
    staging_receipt.same_head(repo, entry)
