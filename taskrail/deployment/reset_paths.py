"""Single deletion inventory for fresh-install validation and execution."""

import json
import os
import sys
from pathlib import Path

from taskrail.infrastructure.agent_profile import FRONTMATTER, MANAGED_DESCRIPTION
from taskrail.infrastructure.opencode_cli import agent_directory

MAIN = (".local/share/taskrail", ".config/taskrail", ".local/state/taskrail")
PRESERVED_STATE = frozenset(("live.lock",))
WORKTREE_BASE = "worktree_base"
EXTRA = (
    ".config/systemd/user/taskrail.service",
    ".config/systemd/user/taskrail.service.d",
    ".local/bin/taskrail",
)


def overlaps(first, second):
    """Protect a source both inside and above a deletion target."""
    return first == second or first in second.parents or second in first.parents


def owned_profiles(options, config, default):
    """Only generated files are removed, never the CLI directory or credentials."""
    configured = Path(options.get("agent_directory", default)).expanduser()
    directory = (config / configured).resolve()
    if directory.is_dir():
        for profile in directory.glob("taskrail-*.md"):
            if profile.is_file() and not profile.is_symlink() and generated(profile):
                yield profile


def generated(profile):
    """Only the generated role's named JSON frontmatter identifies it as ours."""
    header, closing, _ = profile.read_bytes().partition(b"\n---\n")
    opening = FRONTMATTER.encode()
    if not closing or not header.startswith(opening):
        return False
    try:
        front = json.loads(header.removeprefix(opening))
    except ValueError:
        return False
    return (
        isinstance(front, dict)
        and front.get("description") == MANAGED_DESCRIPTION.format(profile.stem)
        and front.get("mode") == "primary"
        and isinstance(front.get("permission"), dict)
    )


class ResetPaths:
    """A complete inventory shared by the preflight and the removal step."""

    def __init__(self, home, profile_directory=None):
        self.home = home.resolve()
        self.main = tuple(self.home / name for name in MAIN)
        self.options = self.read_options()
        self.history = self.history_directory(self.options)
        if profile_directory is not None and not profile_directory.is_absolute():
            raise ValueError("Service profile directory must be absolute")
        default = profile_directory or agent_directory()
        self._profiles = tuple(owned_profiles(self.options, self.main[1], default))
        self.targets = self.removal_paths()

    def read_options(self):
        """An invalid installed configuration cannot authorize removal."""
        settings = self.main[1] / "settings.json"
        options = json.loads(settings.read_text()) if settings.is_file() else {}
        if not isinstance(options, dict):
            raise ValueError("Installed settings must be a JSON object")
        return options

    def history_directory(self, options):
        """Resolve a custom history directory as the runtime does."""
        default = self.main[2] / "runs"
        configured = Path(options.get("run_base", default))
        return self.main[1] / configured.expanduser()

    def removal_paths(self):
        """Every removed directory or file participates in overlap validation."""
        state = self.main[2]
        children = state.iterdir() if state.exists() else ()
        removable = tuple(child for child in children if child.name not in PRESERVED_STATE)
        installation = list(self.main[:2])
        installation.extend(self.home / name for name in EXTRA)
        return (*installation, *removable, self.history, *self._profiles)

    def validate(self, protected, incoming):
        """Reject redirected storage and all release/settings intersections."""
        forbidden = (self.home, Path("/"))
        if self.main[2].resolve() != self.main[2]:
            raise ValueError("Unsafe reset state directory; no files deleted")
        preserved = [self.home / ".local/share/taskrail-worktrees"]
        for options in (self.options, incoming):
            if options.get(WORKTREE_BASE):
                worktrees = Path(options[WORKTREE_BASE]).expanduser()
                preserved.extend((worktrees, worktrees.resolve()))
        validate_history_destination(self.history_directory(incoming))
        for target in self.targets:
            validate_target(target, forbidden, protected, preserved)


def validate_history_destination(path):
    """The replacement service must be able to open or create its history directory."""
    ancestor = path
    while not ancestor.exists() and not ancestor.is_symlink():
        ancestor = ancestor.parent
    writable = os.access(ancestor, os.W_OK | os.X_OK)
    if not ancestor.is_dir() or not writable:
        raise ValueError(f"Run history requires a writable directory: {path}")


def validate_target(target, forbidden, protected, preserved):
    """Check one concrete removal target without expanding a preserved directory."""
    if target.resolve() != target or target in forbidden:
        raise ValueError(f"Unsafe reset path; no files deleted: {target}")
    for source in protected:
        if overlaps(target, source):
            raise ValueError(
                f"Keep installation inputs outside reset directories: {source} overlaps {target}"
            )
    if any(overlaps(target, tree) for tree in preserved):
        raise ValueError("Reset paths overlap preserved worktrees; no files deleted")


def main():
    """Return the CLI's default profile directory in the previous service environment."""
    config = Path(sys.argv[1])
    directory = config / agent_directory().expanduser()
    sys.stdout.write(str(directory.resolve()))
