"""Bind explicitly planned Follow-up files to their pre-task Git versions for review."""

import stat

from taskrail.application import inherited_preimages, worktree_followup
from taskrail.application.planned_paths import safe_file
from taskrail.core import protected_paths
from taskrail.core.files import atomic_write, digest
from taskrail.git import review_source

SELECTED = "followup_selected"
PRESERVED = "followup_preserved"
PREIMAGES = "preimages"
ROOTS = "roots"


def select(workflow):
    """Select pending files by the reviewed Files list of this task or split child."""
    pending = pending_files(workflow.config)
    allowed = set(workflow.flow["allowed"])
    selected = sorted(pending & allowed)
    if pending:
        workflow.state[PRESERVED] = sorted(pending - allowed)
    if selected:
        workflow.state[SELECTED] = selected
        for name in selected:
            bind(workflow, name)
        inherited_preimages.seal(workflow)
    return selected


def bind(workflow, name):
    """Keep bytes and mode from the same HEAD blob across review and continuation."""
    reference, signature, checksum = original(workflow, name)
    workflow.state[PREIMAGES][name] = reference
    workflow.state.setdefault(inherited_preimages.BASELINE, {})[name] = signature
    workflow.state.setdefault(inherited_preimages.INHERITED, {})[name] = checksum


def original(workflow, name):
    """Locate an explicitly approved regular file or deletion in its authenticated root."""
    roots = workflow.config[ROOTS]
    path = safe_file(name, roots, protected_paths.patterns(workflow.config))
    root = roots[name.partition("/")[0]]
    baseline = review_source.head_file(root, path.relative_to(root).as_posix())
    if baseline:
        return save(workflow, name, *baseline)
    return None, None, None


def save(workflow, name, executable, source_bytes):
    """The guard tracks all permission bits while Git tracks only the owner executable bit."""
    reference = f"00-input/preimages/{name}"
    path = workflow.run / reference
    atomic_write(path, source_bytes)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | executable)
    signature = workflow.guard.before.get(name, "644:")
    permissions = int(signature.partition(":")[0], 8)
    permissions = (permissions & ~stat.S_IXUSR) | executable
    checksum = digest(source_bytes)
    signature = format(permissions, "o")
    return reference, f"{signature}:{checksum}", checksum


def paths(workflow, key):
    """Absolute paths for internal permission and Git decisions."""
    found = []
    for name in workflow.state.get(key, []):
        alias, relative = name.split("/", 1)
        found.append(workflow.config[ROOTS][alias] / relative)
    return found


def pending_files(config):
    """Earlier split tasks may already have committed some of the carried paths."""
    found = set()
    for alias, record in config.get("worktrees", {}).items():
        if record.get("carried_files"):
            dirty = review_source.status_names(worktree_followup.status(config[ROOTS][alias]))
            for name in dirty.intersection(record["carried_files"]):
                found.add(f"{alias}/{name}")
    return found
