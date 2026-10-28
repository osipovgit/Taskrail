"""The file system a sandboxed command sees, as bubblewrap mount options.

/tmp, /var/tmp and /run are private and empty, which also hides host sockets. Home is
an empty scratch directory showing, read-only, its visible entries, known toolchain
directories and the installation of the requested program, so credentials in hidden
directories stay out of reach. Protected files in the roots are unreadable and their
Git metadata is read-only.
"""

import os
from pathlib import Path

from taskrail.core import protected_paths

GIT = ".git"
NULL = "/dev/null"
READ_ONLY = "--ro-bind"
TEMPORARY = "--tmpfs"
PRIVATE = ("/tmp", "/var/tmp", "/run")
# Hidden home entries that hold interpreters, package managers and their libraries.
TOOLCHAINS = (
    ".local/bin",
    ".local/lib",
    ".local/share/pipx",
    ".local/share/uv",
    ".local/share/virtualenvs",
    ".pyenv",
    ".conda",
    ".nvm",
    ".volta",
    ".fnm",
    ".bun",
    ".deno",
    ".cargo",
    ".rustup",
    ".sdkman",
    ".jdks",
    ".m2",
    ".gradle",
    ".ivy2",
    ".sbt",
    ".asdf",
    ".rbenv",
    ".gem",
    ".tfenv",
    ".ansible/collections",
    ".ansible/roles",
)


def private():
    """Fresh temporary and runtime directories."""
    existing = filter(os.path.isdir, PRIVATE)
    return [option for path in existing for option in (TEMPORARY, path)]


def home():
    """An empty home with its visible entries and toolchains shown read-only."""
    directory = Path.home()
    options = [TEMPORARY, str(directory)]
    for name in (*visible(directory), *TOOLCHAINS):
        path = str(directory / name)
        options.extend(("--ro-bind-try", path, path))
    return options


def visible(directory):
    """Names of the entries of a directory that are not hidden, sorted."""
    names = (entry.name for entry in os.scandir(directory))
    return sorted(name for name in names if not name.startswith("."))


def installation(program):
    """The program's prefix, such as a virtual environment, read-only wherever it lives.

    A prefix that is home, contains it or is a top-level home entry such as ~/.local
    would reveal more than the program, so only its own directory is shown then.
    """
    path = Path(program)
    if not path.is_absolute():
        return []
    prefix = path.parent.parent
    home_directory = Path.home()
    if home_directory.is_relative_to(prefix) or prefix.parent == home_directory:
        prefix = path.parent
    return [READ_ONLY, str(prefix), str(prefix)]


def project(roots, writable, protected, overlays):
    """The roots, writable, discarding writes or read-only; Git metadata never writable."""
    options = []
    for root in map(str, roots.values()):
        if writable:
            options.extend(("--bind", root, root))
        else:
            options.extend(discarded(root) if overlays else (READ_ONLY, root, root))
    for root in map(Path, roots.values()):
        metadata = str(root / GIT)
        if os.path.exists(metadata):
            options.extend((READ_ONLY, metadata, metadata))
        for secret in hidden(root, protected):
            options.extend((READ_ONLY, NULL, str(secret.resolve())))
    return options


def discarded(directory):
    """Mount options that keep a directory's writes in memory until the command ends."""
    return ["--overlay-src", directory, "--tmp-overlay", directory]


def hidden(root, protected=protected_paths.DEFAULT_PATTERNS):
    """Protected files inside a root, outside its Git metadata."""
    for directory, names, files in os.walk(root):
        if GIT in names:
            names.remove(GIT)
        for name in files:
            path = Path(directory, name)
            if protected_paths.matches(path, protected):
                yield path
