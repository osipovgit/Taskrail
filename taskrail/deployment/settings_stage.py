"""Prepare and validate the configuration before stopping the service."""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from taskrail.application.instruction_sources import ROLES
from taskrail.cli_service import DEFAULT_PORT
from taskrail.deployment import settings_check
from taskrail.infrastructure.opencode_cli import DEFAULT_COMMAND, validate_command

SETTINGS = "settings.json"
ENVIRONMENT = "service.env"
AGENT_SOURCE = "agent_source"
AGENTS = "agents"
PRIVATE_FILE = 0o600
BACKUP_DIGEST_LENGTH = 16
FALLBACK_PATH = "/usr/local/bin:/usr/bin:/bin"
OBSOLETE = frozenset(
    (
        "isolation",
        "max_change_lines",
        "max_change_files",
        "max_repairs",
        "read_retries",
        "max_stage_attempts",
        "stage_timeout_seconds",
        "stop_on_provider_limit",
        "max_observed_tokens",
    )
)


class Installation:
    """Installed operator settings, incoming release, and private staging directory."""

    def __init__(self, arguments):
        self.arguments = arguments
        self.config = arguments.config
        self.prepared = arguments.prepared
        self.bundled = arguments.app / "current/taskrail/agents"
        self.roles = arguments.source / "taskrail/agents"

    def prepare(self):
        """Leave existing settings and the service PATH untouched unless they change."""
        environment = self.config / ENVIRONMENT
        for path in (self.config, self.config / SETTINGS, environment):
            if path.is_symlink():
                raise ValueError(f"Installation configuration must not be redirected: {path}")
        self.prepared.mkdir()
        if self.arguments.fresh or not environment.exists():
            stage_environment(self.prepared)
        self.prepare_settings()

    def prepare_settings(self):
        """Validate the effective settings and copy changes to the staged configuration."""
        target = self.config / SETTINGS
        existing = target.is_file() and not self.arguments.fresh
        original = read_settings(target) if existing else None
        if original is None:
            options = self.first_settings()
        else:
            options = self.existing_settings(original.copy())
        if self.arguments.opencode:
            options["command"] = [self.arguments.opencode]
        if not existing or self.arguments.opencode or self.arguments.apply_settings:
            options["command"] = resolved_command(options)
        remove_obsolete(options)
        settings_check.validate(options, self.config, self.roles)
        if options != original:
            encoded = json.dumps(options, indent=2)
            write_private(self.prepared / SETTINGS, f"{encoded}\n")

    def existing_settings(self, options):
        """Select incoming bundled roles or validate the configured operator sources."""
        if self.arguments.apply_settings:
            options = read_settings(Path(self.arguments.supplied).expanduser())
        source = options.get(AGENT_SOURCE, self.bundled)
        selected = self.config / Path(source).expanduser()
        if selected == self.bundled:
            return options
        if self.arguments.agents == "bundled":
            self.backup_settings(self.config / SETTINGS)
            options[AGENT_SOURCE] = str(self.bundled)
        else:
            self.roles = selected
        return options

    def backup_settings(self, target):
        """A deliberate switch away from custom instructions keeps their exact settings."""
        previous = target.read_bytes()
        fingerprint = hashlib.sha256(previous).hexdigest()[:BACKUP_DIGEST_LENGTH]
        name = f"{SETTINGS}.backup-{fingerprint}"
        if not (self.config / name).exists():
            backup = self.prepared / name
            backup.write_bytes(previous)
            backup.chmod(PRIVATE_FILE)
        destination = self.config / name
        sys.stdout.write(f"Using bundled roles; previous settings saved to {destination}\n")

    def first_settings(self):
        """Resolve imports beside the supplied settings and use bundled roles by default."""
        initial = (
            Path(self.arguments.supplied).expanduser().resolve()
            if self.arguments.supplied
            else self.arguments.source / "taskrail" / SETTINGS
        )
        options = read_settings(initial)
        source = options.get(AGENT_SOURCE)
        if self.arguments.supplied and source is not None and self.arguments.agents == "keep":
            self.import_roles(initial.parent / Path(source).expanduser())
            options[AGENT_SOURCE] = str(self.config / AGENTS)
        else:
            options[AGENT_SOURCE] = str(self.bundled)
        for key in ("agent_directory", "run_base"):
            if self.arguments.supplied and key in options:
                relative = Path(options[key]).expanduser()
                options[key] = str(initial.parent / relative)
        return options

    def import_roles(self, source):
        """Copy only the four active role files, regardless of adjacent local data."""
        installed = self.config / AGENTS
        if installed.exists() and not self.arguments.fresh:
            self.roles = installed
            return
        self.roles = self.prepared / AGENTS
        self.roles.mkdir()
        for role in ROLES:
            name = f"{role}.md"
            if not (source / name).is_file():
                raise ValueError(f"Missing source agent: {role}")
            shutil.copyfile(source / name, self.roles / name)


def remove_obsolete(options):
    """Remove retired keys while retaining configured commands and private extension fields."""
    removed = sorted(OBSOLETE.intersection(options))
    if removed:
        for key in removed:
            options.pop(key)
        sys.stdout.write("Removed obsolete settings: {}\n".format(", ".join(removed)))


def resolved_command(options):
    """Freeze the configured CLI path, retaining the operator's arguments."""
    command = validate_command(options.get("command", list(DEFAULT_COMMAND)))
    executable = shutil.which(command[0])
    if executable is None:
        raise ValueError(f"Agent CLI command not found on PATH: {command[0]}")
    return [str(Path(executable).absolute()), *command[1:]]


def read_settings(path):
    """Settings must be a JSON object before any field can be consumed."""
    options = json.loads(path.read_text())
    if not isinstance(options, dict):
        raise ValueError("Settings must be a JSON object")
    return options


def stage_environment(prepared):
    """Capture the installer PATH for the first service start."""
    captured = os.environ.get("PATH", FALLBACK_PATH)
    if "\n" in captured or "\r" in captured:
        raise ValueError("PATH must not contain newlines")
    quoted = captured.replace("\\", r"\\").replace('"', r"\"")
    write_private(prepared / ENVIRONMENT, f'PATH="{quoted}"\nTASKRAIL_WEB_PORT={DEFAULT_PORT}\n')


def write_private(path, text):
    """The staged file is published with permissions limited to the application user."""
    path.write_text(text)
    path.chmod(PRIVATE_FILE)


def main(argv=None):
    """Installable files remain private in staging until the update is ready."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "config"):
        parser.add_argument(name, type=Path)
    parser.add_argument("supplied")
    parser.add_argument("app", type=Path)
    parser.add_argument("agents", choices=("keep", "bundled"))
    parser.add_argument("prepared", type=Path)
    for name in ("--fresh", "--apply-settings"):
        parser.add_argument(name, action="store_true")
    parser.add_argument("--opencode", metavar="PATH", help="Use this executable for opencode")
    Installation(parser.parse_args(argv)).prepare()


if __name__ == "__main__":
    main()
