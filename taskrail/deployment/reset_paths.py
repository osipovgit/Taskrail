"""Single deletion inventory for fresh-install validation and execution."""

import json
from pathlib import Path

from taskrail.infrastructure.opencode_cli import agent_directory

MAIN = (".local/share/taskrail", ".config/taskrail", ".local/state/taskrail")
PRESERVED_STATE = frozenset(("live.lock", "worktrees"))
EXTRA = (
    ".config/systemd/user/taskrail.service",
    ".config/systemd/user/taskrail.service.d",
    ".local/bin/taskrail",
    ".cache/taskrail",
)


def overlaps(first, second):
    """Protect a source both inside and above a deletion target."""
    return first == second or first in second.parents or second in first.parents


def owned_profiles(options, config):
    """Only generated files are removed, never the CLI directory or credentials."""
    configured = Path(options.get("agent_directory", agent_directory())).expanduser()
    directory = (config / configured).resolve()
    if directory.is_dir():
        for profile in directory.glob("taskrail-*.md"):
            if generated(profile):
                yield profile


def generated(profile):
    """A filename alone cannot authorize deletion of a custom role."""
    if profile.is_symlink() or not profile.is_file():
        return False
    return "Managed Taskrail workflow" in profile.read_text(encoding="utf-8")


class ResetPaths:
    """A complete inventory shared by the preflight and the removal step."""

    def __init__(self, home):
        self.home = home.resolve()
        self.main = tuple(self.home / name for name in MAIN)
        self.options = self.read_options()
        self.history = self.history_directory()
        self.profiles = tuple(owned_profiles(self.options, self.main[1]))

    def read_options(self):
        """An invalid installed configuration cannot authorize removal."""
        settings = self.main[1] / "settings.json"
        options = json.loads(settings.read_text()) if settings.is_file() else {}
        if not isinstance(options, dict):
            raise ValueError("Installed settings must be a JSON object")
        return options

    def history_directory(self):
        """Resolve a custom history directory as the runtime does."""
        default = self.main[2] / "runs"
        configured = Path(self.options.get("run_base", default))
        return self.main[1] / configured.expanduser()

    def targets(self):
        """Every removed directory or file participates in overlap validation."""
        extras = tuple(self.home / name for name in EXTRA)
        state = self.main[2]
        children = state.iterdir() if state.exists() else ()
        removable = tuple(child for child in children if child.name not in PRESERVED_STATE)
        additional = (self.history, *extras, *self.profiles)
        return (*self.main[:2], *removable, *additional)

    def validate(self, protected):
        """Reject redirected storage and all release/settings intersections."""
        forbidden = (self.home, Path("/"))
        if self.main[2].resolve() != self.main[2]:
            raise ValueError("Unsafe reset state directory; no files deleted")
        worktrees = self.main[2] / "worktrees"
        preserved = [worktrees]
        if self.options.get("worktree_base"):
            preserved.append(Path(self.options["worktree_base"]).expanduser().resolve())
        for target in self.targets():
            validate_target(target, forbidden, protected, preserved)


def validate_target(target, forbidden, protected, preserved):
    """Check one concrete removal target without expanding a preserved directory."""
    if target.resolve() != target or target in forbidden:
        raise ValueError(f"Unsafe reset path; no files deleted: {target}")
    if any(overlaps(target, source) for source in protected):
        raise ValueError("Extract release and supplied settings outside reset directories")
    if any(overlaps(target, source) for source in preserved):
        raise ValueError("Reset paths overlap preserved worktrees; no files deleted")
