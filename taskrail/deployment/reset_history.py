"""Read declared roots from live, archived and never-started task histories."""

from taskrail.deployment.reset_records import (
    LAUNCH_INDEX,
    RUN_INDEX,
    declared_roots,
    document,
    launch_roots,
)


def children(directory):
    """Only real directories can be application-owned record containers."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Unsafe history directory: {directory}")
    for child in directory.iterdir():
        if child.is_symlink() or not child.is_dir():
            raise ValueError(f"History contains unrecognized files: {child}")
        yield child


def record_roots(folder):
    """Identify a run or launcher before accepting its contents for removal."""
    if (folder / RUN_INDEX).exists():
        return declared_roots(document(folder / RUN_INDEX))
    if (folder / LAUNCH_INDEX).exists():
        return launch_roots(folder)
    raise ValueError(f"History contains unrecognized files: {folder}")


def history_roots(history):
    """Archived runs keep the same ownership checks as visible runs."""
    if not history.exists():
        return
    for child in children(history):
        if child.name == ".trash":
            yield from collection_roots(child, archived=True)
        elif child.name == ".submissions":
            yield from collection_roots(child)
        else:
            yield from record_roots(child)


def collection_roots(directory, archived=False):
    """Trash adds one grouping level around runs and their launcher records."""
    for record in children(directory):
        if archived:
            yield from collection_roots(record)
        else:
            yield from record_roots(record)
