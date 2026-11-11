"""First-run settings and a health check of the opencode integration; no project is touched."""

import json
import shutil
import sys
from pathlib import Path
from types import MappingProxyType

from taskrail import cli_health
from taskrail.core.files import bounded_bytes
from taskrail.core.runtime import settings_path
from taskrail.infrastructure.opencode_settings import launch_settings

ROLES = ("planner", "implementer", "reviewer")
CHECK_MARKER = "cli-check.sha256"
COMMAND = "command"
PRIVATE_FILE = 0o600
MODEL_QUESTIONS = MappingProxyType(
    {role: f"{role} model (provider/model, Enter = opencode default)" for role in ROLES}
)


def check(explicit=None):
    """Return (passed, message) pairs for settings, opencode, permissions and storage."""
    path = settings_path(explicit)
    found = (True, f"Settings: {path}" if path.is_file() else "Settings: bundled defaults")
    try:
        options = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError) as error:
        return [found, (False, f"Settings are unreadable: {error}"), *cli_health.host_results()]
    try:
        connection = cli_health.Connection.from_settings(options, path.parent)
    except ValueError as error:
        return [found, (False, str(error)), *cli_health.host_results()]
    return [found, *connection.diagnostics()]


def check_connection(options, base, *, force=False):
    """Verify installation settings and return the digest to publish after a successful install."""
    connection = cli_health.Connection.from_settings(options, base)
    current = connection.fingerprint()
    if not force and checked(base / CHECK_MARKER, current):
        return None
    failures = [message for passed, message in connection.diagnostics() if not passed]
    if failures:
        raise ValueError("\n".join(failures))
    return current


def checked(marker, current):
    previous = bounded_bytes(marker, len(current) + 1)
    return previous in (current.encode(), f"{current}\n".encode())


def init(opencode=None, models=(), force=False):
    """Write user settings from the bundled defaults; arguments override, prompts fill gaps."""
    target = Path.home() / ".config/taskrail/settings.json"
    if target.exists() and not force:
        raise ValueError(f"{target} exists; use --force to replace it")
    settings = json.loads(Path(__file__).with_name("settings.json").read_text())
    settings.pop("agent_source", None)
    default = shutil.which("opencode") or "opencode"
    settings[COMMAND] = [opencode or ask("opencode command", default)]
    settings["models"] = role_models(models)
    launch_settings(settings, target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{json.dumps(settings, indent=2)}\n")
    target.chmod(PRIVATE_FILE)
    return target


def role_models(entries):
    """ROLE=provider/model entries; missing roles are asked, Enter keeps opencode's default."""
    chosen = dict(entry.split("=", 1) for entry in entries)
    missing = [role for role in ROLES if role not in chosen]
    for role in missing:
        chosen[role] = ask(MODEL_QUESTIONS[role], "")
    return {name: model for name, model in chosen.items() if model}


def ask(question, default):
    """Prompt only on a terminal; otherwise keep the default."""
    if not sys.stdin.isatty():
        return default
    sys.stdout.write(f"{question} [{default}]: ")
    sys.stdout.flush()
    return sys.stdin.readline().strip() or default
