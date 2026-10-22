"""Fingerprint small Git control files; never read objects or invoke Git."""

from countersign.application.git_reference import git_reference
from countersign.core.files import digest

CONTROL_FILES = ("HEAD", "index", "config", "packed-refs", "ORIG_HEAD", "commondir")
GITDIR = "gitdir: "
SYMBOLIC = "ref: "


def git_metadata(roots):
    """Detect any Git state change made outside the controlled executor."""
    fingerprints = {}
    for alias, root in roots.items():
        fingerprints.update(root_metadata(alias, git_reference(root)))
    return fingerprints


def root_metadata(alias, reference):
    """Include a `.git` pointer file and the control files it leads to."""
    fingerprints = {}
    git = reference
    if reference.is_file():
        fingerprints[f"{alias}/.git"] = digest(reference.read_bytes())
        git = linked_directory(reference)
    if git.is_dir():
        for index, candidates in enumerate(control_sets(git)):
            fingerprints.update(control_metadata(f"{alias}/{index}", candidates))
    return fingerprints


def linked_directory(reference):
    """Follow a worktree or submodule `.git` file to its Git directory."""
    pointer = reference.read_text().strip()
    if pointer.startswith(GITDIR):
        return reference.parent.joinpath(pointer.removeprefix(GITDIR)).resolve()
    return reference


def control_sets(git):
    """A linked worktree tracks its own files, shared config and its branch ref only.

    Other branches and the main checkout may change while an isolated run works.
    """
    common = git / "commondir"
    own = (git, own_files(git))
    if not common.is_file():
        return [own]
    shared = git.joinpath(common.read_text().strip()).resolve()
    branch = [shared / name for name in branch_refs(git)]
    return [own, (shared, [shared / "config", *branch])]


def own_files(control):
    """Fixed control files and loose refs of one Git directory."""
    candidates = [control / name for name in CONTROL_FILES]
    refs = control / "refs"
    if refs.exists():
        candidates.extend(refs.rglob("*"))
    return candidates


def branch_refs(git):
    """The checked-out branch of a linked worktree; none when detached."""
    head = git.joinpath("HEAD").read_text().strip()
    if head.startswith(SYMBOLIC):
        return [head.removeprefix(SYMBOLIC)]
    return []


def control_metadata(prefix, candidates):
    """Hash the existing control files of one Git directory."""
    control, paths = candidates
    return {
        "{0}/{1}".format(prefix, path.relative_to(control)): digest(path.read_bytes())
        for path in paths
        if path.is_file()
    }
