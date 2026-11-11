"""Preimages and the reviewable diff of approved in-place edits."""

import difflib

from taskrail.application import followup_selection
from taskrail.application.planned_paths import safe_file
from taskrail.core.files import atomic_write
from taskrail.git import review_source

DEV_NULL = "/dev/null"
NO_NEWLINE = r"\ No newline at end of file"
NUL = b"\0"


def capture(workflow):
    """Bind carried changes to HEAD and ordinary files to their current working bytes."""
    selected = followup_selection.select(workflow)
    ordinary = sorted(set(workflow.flow["allowed"]) - set(selected))
    capture_preimages(workflow.run, workflow.config["roots"], ordinary, workflow.state["preimages"])


def capture_preimages(run, roots, allowed, preimages):
    """Store the original bytes of every approved file before the first edit."""
    for name in allowed:
        original = safe_file(name, roots)
        reference = None
        if original.exists():
            reference = f"00-input/preimages/{name}"
            atomic_write(run / reference, original.read_bytes())
        preimages[name] = reference


def write_diff(workflow):
    """Write changes.diff from preimages to current bytes."""
    selected = set(workflow.state.get("followup_selected", []))
    chunks = (review_patch(workflow, name, selected) for name in workflow.state["preimages"])
    (workflow.run / "changes.diff").write_text("".join(chunks), encoding="utf-8")


def review_patch(workflow, name, selected):
    """A carried file uses its complete Git patch for every review and continuation."""
    roots = workflow.config["roots"]
    path = safe_file(name, roots)
    stored = workflow.state["preimages"][name]
    if name in selected:
        original = workflow.run / stored if stored else None
        root = roots[name.partition("/")[0]]
        return review_source.full_patch(root, original, path)
    return file_diff(workflow.run, path, stored)


def file_diff(run, path, stored):
    """Unified diff of one file; binary content is only reported as changed."""
    before = run.joinpath(stored).read_bytes() if stored else b""
    after = path.read_bytes() if path.exists() else b""
    if before == after:
        return ""
    if NUL in before or NUL in after:
        return f"Binary file changed: {path}\n"
    lines = difflib.unified_diff(
        text_lines(before),
        text_lines(after),
        fromfile=str(path) if stored else DEV_NULL,
        tofile=str(path) if path.exists() else DEV_NULL,
    )
    return "".join(terminated(line) for line in lines)


def text_lines(source_bytes):
    """Decode leniently, keeping line endings for an exact diff."""
    return source_bytes.decode("utf-8", "replace").splitlines(keepends=True)


def terminated(line):
    """Mark a final line without a newline the way Git does."""
    if line.endswith("\n"):
        return line
    return f"{line}\n{NO_NEWLINE}\n"
