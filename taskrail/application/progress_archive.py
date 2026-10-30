"""Bound working progress notes without discarding their original bytes."""

from taskrail.core import prompt_texts
from taskrail.core.files import digest
from taskrail.infrastructure.agent_sync import atomic_write

DIRECTORY = "00-input/progress-archive"
MAX_BYTES = 8192


def bound(run, target):
    """Retain the beginning and latest notes, with an exact archived original."""
    if target.stat().st_size <= MAX_BYTES:
        return
    source = target.read_bytes()
    archive = run / DIRECTORY / f"{digest(source)}.md"
    archive.parent.mkdir(exist_ok=True, parents=True)
    atomic_write(archive, source)
    notice = prompt_texts.text("progress.bounded", archive=archive).encode()
    atomic_write(target, excerpts(source, notice))


def excerpts(source, notice):
    """Leave whole UTF-8 characters at the bounded excerpt edges."""
    half = max(0, MAX_BYTES - len(notice)) // 2
    beginning = source[:half].decode("utf-8", errors="ignore").encode()
    ending = source[-half:] if half else b""
    return beginning + notice + ending.decode("utf-8", errors="ignore").encode()


def paths(run):
    """Only exact files of this run are readable; no directory permission is granted."""
    candidates = sorted((run / DIRECTORY).glob("*.md"))
    return [path for path in candidates if path.is_file() and not path.is_symlink()]
