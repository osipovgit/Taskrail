"""Initialize persistent configuration once; updates preserve user settings and roles."""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from taskrail.cli_service import DEFAULT_PORT
from taskrail.deployment import rename
from taskrail.infrastructure.opencode_cli import DEFAULT_COMMAND, validate_command

SETTINGS = "settings.json"
PRIVATE_FILE = 0o600
FIRST_TIMEOUT_SECONDS = 3600
BACKUP_DIGEST_LENGTH = 16
FALLBACK_PATH = "/usr/local/bin:/usr/bin:/bin"
IMPORTED_FOLDERS = ("agent_directory", "run_base")
AGENT_SOURCE = "agent_source"


class Installation:
    """The extracted release, the persistent configuration and the application folder."""

    def __init__(self, source, config, app):
        self.source = source
        self.config = config
        self.target = config / SETTINGS
        self.bundled_agents = str(app / "current/taskrail/agents")

    def initialize(self, supplied):
        """Write first-install settings; an existing file is kept but must parse."""
        if self.target.exists():
            json.loads(self.target.read_text())
        else:
            write_private(self.target, self.first_settings(supplied))

    def first_settings(self, supplied):
        """Bundled defaults or an imported file, with the agent CLI resolved at install time."""
        if supplied:
            initial = Path(supplied).expanduser().resolve()
        else:
            initial = self.source / "taskrail" / SETTINGS
        settings = json.loads(initial.read_text())
        settings["timeout_seconds"] = FIRST_TIMEOUT_SECONDS
        settings["command"] = resolved(settings.get("command", list(DEFAULT_COMMAND)))
        if supplied:
            self.import_folders(settings, initial.parent)
        else:
            settings[AGENT_SOURCE] = self.bundled_agents
        return settings

    def import_folders(self, settings, origin):
        """Copy imported roles once; other relative folders keep the imported file's meaning."""
        roles = self.config / "agents"
        if not roles.exists():
            shutil.copytree(absolute(settings.get(AGENT_SOURCE, "agents"), origin), roles)
        settings[AGENT_SOURCE] = str(roles)
        for key in IMPORTED_FOLDERS:
            folder = settings.get(key)
            if folder is not None:
                settings[key] = str(absolute(folder, origin))

    def use_bundled_agents(self):
        """Point settings at the release roles after keeping one backup per distinct file."""
        previous = self.target.read_bytes()
        settings = json.loads(previous)
        settings[AGENT_SOURCE] = self.bundled_agents
        digest = hashlib.sha256(previous).hexdigest()[:BACKUP_DIGEST_LENGTH]
        backup = self.config / f"{SETTINGS}.backup-{digest}"
        if not backup.exists():
            backup.write_bytes(previous)
            backup.chmod(PRIVATE_FILE)
        temporary = self.config / f"{SETTINGS}.next"
        write_private(temporary, settings)
        temporary.replace(self.target)
        sys.stdout.write(f"Using bundled roles; previous settings saved to {backup}\n")


def resolved(command):
    """The service must not depend on the installer's PATH to find the agent CLI."""
    executable = shutil.which(validate_command(command)[0])
    if executable is None:
        raise ValueError(f"Agent CLI command not found on PATH: {command[0]}")
    return [executable, *command[1:]]


def absolute(folder, origin):
    """A relative folder is relative to the settings file that names it."""
    path = Path(folder).expanduser()
    return path if path.is_absolute() else origin / path


def service_environment(config):
    """Capture the installer's PATH once so the user service finds the same tools."""
    environment = config / "service.env"
    if environment.exists():
        return
    captured = os.environ.get("PATH", FALLBACK_PATH)
    if "\n" in captured or "\r" in captured:
        raise ValueError("PATH must not contain newlines")
    quoted = captured.replace("\\", r"\\").replace('"', r"\"")
    environment.write_text(f'PATH="{quoted}"\nTASKRAIL_WEB_PORT={DEFAULT_PORT}\n')
    environment.chmod(PRIVATE_FILE)


def write_private(path, settings):
    """Configuration stays readable by the application user only."""
    encoded = json.dumps(settings, indent=2)
    path.write_text(f"{encoded}\n")
    path.chmod(PRIVATE_FILE)


def parsed(argv):
    """Positional arguments in the order deploy/install.sh passes them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("supplied")
    parser.add_argument("app", type=Path)
    parser.add_argument("agents", choices=("keep", "bundled"))
    return parser.parse_args(argv)


def main(argv=None):
    """Create settings and the service environment once; switch roles only when asked."""
    arguments = parsed(argv)
    rename.follow(arguments.config)
    installation = Installation(arguments.source, arguments.config, arguments.app)
    installation.initialize(arguments.supplied)
    if arguments.agents == "bundled":
        installation.use_bundled_agents()
    service_environment(arguments.config)


if __name__ == "__main__":
    main()
