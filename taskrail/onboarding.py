"""First-run settings and a health check of the opencode integration; no project is touched."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import MappingProxyType

from taskrail.core.runtime import run_storage, settings_path
from taskrail.infrastructure import opencode_cli
from taskrail.infrastructure.agent_profile import make_profile
from taskrail.infrastructure.agent_sync import launch_settings
from taskrail.infrastructure.permission_check import verify_launch

ROLES = ("planner", "implementer", "reviewer")
PROBE = "taskrail-check"
COMMAND = "command"
VERSION_SECONDS = 30
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
        return [found, (False, f"Settings are unreadable: {error}")]
    try:
        launch = launch_settings(options, path.parent)
    except (OSError, ValueError) as error:
        return [found, (False, f"Settings are invalid: {error}")]
    command = options.get(COMMAND, list(opencode_cli.DEFAULT_COMMAND))
    return [
        found,
        version_result(command, launch["opencode_version"], launch["agent_env_allow"]),
        permission_result(launch),
        storage_result(explicit),
    ]


def version_result(command, version, allow=()):
    try:
        completed = subprocess.run(
            [*command, "--version"],
            env=opencode_cli.environment(allow),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=VERSION_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"opencode is not runnable ({command[0]}): {error}"
    reported = completed.stdout.strip().partition("\n")[0] or "no version output"
    message = f"opencode CLI {reported} via {command[0]} ({version} interface)"
    return completed.returncode == 0, message


def permission_result(launch):
    """A closed throwaway profile must come back exactly as written."""
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        (workspace / "role.md").write_text("Health check profile; never used for a model run.\n")
        access = dict(roots=[workspace], readable=[], writable=[])
        profile, rules = make_profile(workspace / "role.md", launch["destination"], PROBE, access)
        try:
            verify_launch(launch, workspace, PROBE, rules, workspace / "log")
        except (OSError, ValueError) as error:
            return False, f"Permission enforcement could not be verified: {error}"
        finally:
            profile.unlink(missing_ok=True)
    return True, "Permission rules enforced; profiles in {}".format(launch["destination"])


def storage_result(explicit):
    runs = run_storage(explicit)
    try:
        runs.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return False, f"Run history is not writable ({runs}): {error}"
    return True, f"Run history: {runs}"


def init(opencode=None, models=(), repair=None, force=False):
    """Write user settings from the bundled defaults; arguments override, prompts fill gaps."""
    target = Path.home() / ".config/taskrail/settings.json"
    if target.exists() and not force:
        raise ValueError(f"{target} exists; use --force to replace it")
    settings = json.loads(Path(__file__).with_name("settings.json").read_text())
    settings.pop("agent_source", None)
    default = shutil.which("opencode") or "opencode"
    settings[COMMAND] = [opencode or ask("opencode command", default)]
    settings["models"] = role_models(models)
    settings["format_repair_tools"] = repair or ask("format repair tools (none/read)", "none")
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
