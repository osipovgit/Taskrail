"""Mandatory credential masks for every path mounted into a local command sandbox."""

import os
import re
from fnmatch import translate
from pathlib import Path

from taskrail.core import protected_paths

USER_CONFIG = ".config"
DIRECTORIES = frozenset((".ssh", ".aws", ".azure", USER_CONFIG, ".docker", ".kube", ".gnupg"))
CREDENTIAL_DIRECTORIES = DIRECTORIES - {USER_CONFIG}
CONFIGURATIONS = (
    "settings.xml",
    "settings-security.xml",
    "gradle.properties",
    "credentials",
    "credentials.toml",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".yarnrc*",
    "pip.conf",
    "pip.ini",
    "nuget.config",
    "NuGet.Config",
    ".gemrc",
    "auth.json",
    ".cargo/config",
    ".cargo/config.toml",
    ".git/config",
    ".git/config.worktree",
)
MANDATORY = protected_paths.read_patterns((*protected_paths.DEFAULTS, *CONFIGURATIONS))


def private(path, resolved=None, project=False):
    """Credential directories and aliases to them stay closed even below tool paths."""
    if resolved is None:
        resolved = path.resolve()
    names = (*path.parts, *resolved.parts)
    if project and USER_CONFIG in names:
        home_config = Path.home() / USER_CONFIG
        if not any(name.is_relative_to(home_config) for name in (path, resolved)):
            return bool(CREDENTIAL_DIRECTORIES.intersection(names))
    return bool(DIRECTORIES.intersection(names))


def masks(roots, protected, project=False):
    """Apply masks last; a custom root or tool prefix cannot restore these contents."""
    options = []
    for path, resolved in hidden(roots, (*MANDATORY, *protected), project):
        options.extend(mask(path, resolved))
    return options


def mask(path, resolved):
    """Cover bind aliases; real symlinks follow their masked canonical target."""
    options = []
    targets = (resolved,) if path.is_symlink() else (resolved, path)
    for target in map(str, dict.fromkeys(targets)):
        if path.is_dir():
            options.extend(("--tmpfs", target, "--remount-ro", target))
        else:
            options.extend(("--ro-bind", "/dev/null", target))
    return options


def hidden(roots, protected, project=False):
    """Walk runtime files without following directory aliases or credential subtrees."""
    masked = set()
    expression = re.compile("|".join(map(translate, protected)))
    for root in dict.fromkeys(map(Path, roots)):
        for path, resolved in candidates(root, project):
            if secret(path, resolved, expression, project) and path not in masked:
                masked.add(path)
                yield path, resolved


def secret(path, resolved, expression, project):
    """Match each distinct visible or canonical name without resolving normal files."""
    return private(path, resolved, project) or any(
        expression.fullmatch(str(name)) for name in dict.fromkeys((path, resolved))
    )


def candidates(root, project):
    """Resolve each directory once per scan; symlink entries still resolve individually."""
    if not root.is_dir():
        yield root, root.resolve()
        return
    for walked in os.walk(root):
        yield from entries(walked, project)


def entries(walked, project):
    """One os.walk directory with canonical names and private subdirectories pruned."""
    canonical = Path(walked[0]).resolve()
    for name in (*walked[1], *walked[2]):
        path = Path(walked[0], name)
        resolved = path.resolve() if path.is_symlink() else canonical / name
        if name in walked[1] and private(path, resolved, project):
            walked[1].remove(name)
        yield path, resolved
