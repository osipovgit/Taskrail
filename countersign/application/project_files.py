"""The source files of a declared root and their landmarks, read once before planning.

Files come from Git (tracked and untracked ones, never ignored ones) or, outside a
repository, from a walk that skips tool and dependency directories. Protected files
and large or binary files are listed without their content.
"""

import os
import re
from fnmatch import fnmatch
from pathlib import Path
from types import MappingProxyType

from countersign.git import process
from countersign.infrastructure.artifact_access import PROTECTED_READ_PATTERNS

SKIPPED = frozenset(
    (".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".idea", "dist", "build")
)
MAX_BYTES = 1000000
BINARY_PROBE = 4096
LANDMARK_LIMIT = 8
LANDMARK_CHARACTERS = 60
YAML_TASK = re.compile(r"(?m)^\s*- name:\s*(.+)$")
YAML_KEY = re.compile(r"(?m)^([A-Za-z_][\w.-]*):")
YAML = (YAML_TASK, YAML_KEY)
LANDMARKS = MappingProxyType(
    {
        ".py": (re.compile(r"(?m)^\s*(?:async\s+)?(?:def|class)\s+(\w+)"),),
        ".yml": YAML,
        ".yaml": YAML,
        ".md": (re.compile(r"(?m)^(#{1,3}\s+.+)$"),),
        ".sh": (re.compile(r"(?m)^(?:function\s+)?([\w-]+)\s*\(\)"),),
        ".js": (re.compile(r"(?m)^(?:export\s+)?(?:async\s+)?function\s+(\w+)"),),
    }
)


def listing(root):
    """Paths of the root's source files relative to it, sorted; protected ones left out."""
    names = git_files(root)
    if names is None:
        names = walked(root)
    return sorted(name for name in names if not protected(name))


def git_files(root):
    """Tracked and untracked files without ignored ones, or None outside a repository."""
    outcome = process.invoke(root, ["ls-files", "-co", "--exclude-standard", "-z"])
    if outcome.returncode != 0:
        return None
    return [name for name in outcome.stdout.split("\x00") if name]


def walked(root):
    """Every file below the root, without tool and dependency directories."""
    found = []
    for directory, folders, files in os.walk(root):
        found.extend(directory_files(root, directory, folders, files))
    return found


def directory_files(root, directory, folders, files):
    """The files of one walked directory; its skipped subdirectories are not entered."""
    for skipped in SKIPPED.intersection(folders):
        folders.remove(skipped)
    base = Path(directory).relative_to(root)
    return [base.joinpath(file_name).as_posix() for file_name in files]


def protected(name):
    """A file the model may never read, such as .env."""
    return any(fnmatch(f"/{name}", pattern) for pattern in PROTECTED_READ_PATTERNS)


def described(path):
    """(line count, landmarks, text) of a text file, or None for a large or binary one."""
    regular = path.is_file() and not path.is_symlink()
    if not regular or path.stat().st_size > MAX_BYTES:
        return None
    raw = path.read_bytes()
    if b"\x00" in raw[:BINARY_PROBE]:
        return None
    text = raw.decode("utf-8", errors="replace")
    marks = landmarks(path.suffix.lower(), text)
    return len(text.splitlines()), marks, text


def landmarks(suffix, text):
    """The first task names, keys, definitions or headings of a file, clipped."""
    marks = []
    for pattern in LANDMARKS.get(suffix, ()):
        marks.extend(pattern.findall(text))
    return [mark.strip()[:LANDMARK_CHARACTERS] for mark in marks[:LANDMARK_LIMIT]]
