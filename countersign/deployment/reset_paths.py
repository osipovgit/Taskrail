"""Single deletion inventory for fresh-install validation and execution."""

import json
from pathlib import Path

from countersign.infrastructure.opencode_cli import agent_directory

MAIN = (".local/share/countersign", ".config/countersign", ".local/state/countersign")
EXTRA = (
    ".config/systemd/user/countersign.service",
    ".config/systemd/user/countersign.service.d",
    ".local/bin/countersign",
    ".cache/countersign",
)


def overlaps(first, second):
    """Protect a source both inside and above a deletion target."""
    return first == second or first in second.parents or second in first.parents


def owned_profiles(options, config):
    """Only generated files are removed, never the CLI directory or credentials."""
    configured = Path(options.get("agent_directory", agent_directory())).expanduser()
    directory = (config / configured).resolve()
    if directory.is_dir():
        for profile in directory.glob("countersign-*.md"):
            if generated(profile):
                yield profile


def generated(profile):
    """A filename alone cannot authorize deletion of a custom role."""
    if profile.is_symlink() or not profile.is_file():
        return False
    return "Managed Countersign workflow" in profile.read_text(encoding="utf-8")


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
        return (*self.main, self.history, *extras, *self.profiles)

    def validate(self, protected):
        """Reject redirected storage and all release/settings intersections."""
        forbidden = (self.home, Path("/"))
        for target in self.targets():
            if target.resolve() != target or target in forbidden:
                raise ValueError(f"Unsafe reset path; no files deleted: {target}")
            if any(overlaps(target, source) for source in protected):
                raise ValueError("Extract release and supplied settings outside reset directories")
