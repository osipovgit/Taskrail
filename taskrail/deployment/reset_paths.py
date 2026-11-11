"""Single deletion inventory for fresh-install validation and execution."""

import json
import os
import shutil
from pathlib import Path

from taskrail.application.instruction_sources import ROLES
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

    def __init__(self, home, keep_config=None):
        self.home = home.resolve()
        self.main = tuple(self.home / name for name in MAIN)
        self.options = self.read_options()
        self.history = self.history_directory(self.options)
        self._profiles = tuple(owned_profiles(self.options, self.main[1]))
        self.retained = None
        if keep_config:
            self.retained = (
                json.loads(keep_config.read_text()) if keep_config.is_file() else self.options
            )
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
        installation = [self.main[0]]
        if self.retained is None:
            installation.append(self.main[1])
            installation.extend(self.home / name for name in EXTRA)
        return (*installation, *removable, self.history, *self._profiles)

    def validate(self, protected):
        """Reject redirected storage and all release/settings intersections."""
        forbidden = (self.home, Path("/"))
        if self.main[2].resolve() != self.main[2]:
            raise ValueError("Unsafe reset state directory; no files deleted")
        preserved = [self.home / ".local/share/taskrail-worktrees"]
        if self.options.get(WORKTREE_BASE):
            preserved.append(Path(self.options[WORKTREE_BASE]).expanduser().resolve())
        if self.retained is not None:
            protected = [*protected, *self.config_inputs()]
            validate_history_destination(self.history_directory(self.retained))
        for target in self.targets:
            validate_target(target, forbidden, protected, preserved)

    def config_inputs(self):
        """Protect settings, the selected executable and custom roles during a force update."""
        config = self.main[1]
        yield config / "settings.json"
        yield config / "service.env"
        yield from (self.home / name for name in EXTRA)
        options = self.retained
        if options.get(WORKTREE_BASE):
            yield Path(options[WORKTREE_BASE]).expanduser().resolve()
        bundled = self.main[0] / "current/taskrail/agents"
        roles = config / Path(options.get("agent_source", bundled)).expanduser()
        if roles != bundled:
            yield roles.resolve()
            yield from ((roles / f"{role}.md").resolve() for role in ROLES)
        yield from command_paths(options.get("command", ["opencode"]))


def command_paths(command):
    """Paths in the saved argv must survive replacement of application files."""
    executable = shutil.which(command[0])
    if executable:
        yield Path(executable).resolve()
    for argument in map(Path, command[1:]):
        if argument.is_absolute():
            yield argument.resolve()


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
    if any(overlaps(target, source) for source in protected):
        raise ValueError("Extract release and supplied settings outside reset directories")
    if any(overlaps(target, source) for source in preserved):
        raise ValueError("Reset paths overlap preserved worktrees; no files deleted")
