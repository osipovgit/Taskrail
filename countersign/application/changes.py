"""Preimages and the reviewable diff of approved in-place edits."""

import difflib

from countersign.application.planned_paths import safe_file
from countersign.infrastructure.agent_sync import atomic_write

DEV_NULL = "/dev/null"
NO_NEWLINE = r"\ No newline at end of file"
NUL = b"\0"


def capture_preimages(run, roots, allowed, preimages):
    """Store the original bytes of every approved file before the first edit."""
    for name in allowed:
        original = safe_file(name, roots)
        reference = None
        if original.exists():
            reference = f"00-input/preimages/{name}"
            atomic_write(run / reference, original.read_bytes())
        preimages[name] = reference


def write_diff(run, roots, preimages):
    """Write changes.diff from preimages to current bytes."""
    chunks = []
    for name, stored in preimages.items():
        chunks.append(file_diff(run, safe_file(name, roots), stored))
    (run / "changes.diff").write_text("".join(chunks), encoding="utf-8")


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
