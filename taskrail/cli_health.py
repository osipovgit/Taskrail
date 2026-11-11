"""CLI and host diagnostics shared by installation and taskrail check."""

import json
import os
import stat
import tempfile
from pathlib import Path

from taskrail.application import yaml_install
from taskrail.core.files import digest
from taskrail.core.runtime import configured_storage
from taskrail.infrastructure import opencode_api, opencode_cli, sandbox
from taskrail.infrastructure.agent_profile import make_profile
from taskrail.infrastructure.opencode_settings import command_paths, profile_settings
from taskrail.infrastructure.permission_check import verify_launch

CONFIG_FILE = "OPENCODE_CONFIG"
CLI_ENV = (
    "HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "OPENCODE_CONFIG_DIR",
    CONFIG_FILE,
    "OPENCODE_CONFIG_CONTENT",
)


class Connection:
    """The resolved CLI profile and run storage shared by manual and installation checks."""

    def __init__(self, options, base):
        if not isinstance(options, dict):
            raise ValueError("expected a JSON object")
        self.profile = profile_settings(options, base)
        self.runs = configured_storage(options, base)
        names = (*CLI_ENV, *options.get("agent_env_allow", []))
        self.environment = {name: os.environ.get(name) for name in names}

    @classmethod
    def from_settings(cls, options, base):
        try:
            return cls(options, base)
        except (OSError, TypeError, ValueError) as error:
            raise ValueError(f"Settings are invalid: {error}") from error

    def fingerprint(self):
        """Recheck changed CLI files and profile settings, including XDG defaults."""
        paths = list(command_paths(self.profile["command"]))
        configured = self.environment[CONFIG_FILE]
        if configured and Path(configured).is_absolute():
            paths.append(Path(configured))
        inputs = dict(
            self.profile,
            agent_env_allow=sorted(set(self.profile["agent_env_allow"])),
            tool_output_dir=opencode_cli.tool_output_pattern(self.profile["tool_output_dir"]),
            run_base=str(self.runs),
            cli_files=[file_identity(path) for path in paths],
            environment=self.environment,
        )
        return digest(json.dumps(inputs, sort_keys=True, default=str).encode())

    def diagnostics(self):
        """Only a runnable CLI with its expected permission policy passes."""
        try:
            checks = probe_cli(self.profile)
        except (OSError, ValueError) as error:
            checks = [(False, str(error))]
        return [*checks, self.storage_result(), *host_results()]

    def storage_result(self):
        try:
            self.verify_storage()
        except OSError as error:
            return False, f"Run history is not writable ({self.runs}): {error}"
        return True, f"Run history: {self.runs}"

    def verify_storage(self):
        self.runs.mkdir(parents=True, exist_ok=True)
        tempfile.TemporaryFile(dir=self.runs).close()


def file_identity(path):
    try:
        metadata = path.stat()
    except OSError:
        return None
    if stat.S_ISREG(metadata.st_mode):
        return str(path.resolve()), metadata.st_ino, metadata.st_size, metadata.st_ctime_ns
    return None


def host_results():
    """These report available local tools with their normal diagnostic severity."""
    return yaml_install.health(), sandbox.health()


def probe_cli(profile):
    command = profile["command"]
    completed = opencode_api.reported_version(command, profile["agent_env_allow"])
    version = profile["opencode_version"]
    if version == opencode_api.AUTO:
        version = opencode_api.detected(completed)
    reported = completed.stdout.strip().partition("\n")[0] or "no version output"
    message = f"opencode CLI {reported} via {command[0]} ({version} interface)"
    if completed.returncode:
        return [(False, f"{message}; --version exited with code {completed.returncode}")]
    return [
        (True, message),
        permission_result(dict(profile, command=opencode_api.launch_command(command, version))),
    ]


def permission_result(launch):
    """Use a private temporary name so concurrent checks and user profiles are isolated."""
    with tempfile.TemporaryDirectory(prefix="taskrail-check-") as directory:
        workspace = Path(directory)
        profile, rules = create_profile(launch["destination"], workspace)
        try:
            verify_launch(launch, workspace, workspace.name, rules, workspace / "log")
        except (OSError, ValueError) as error:
            return False, f"Permission enforcement could not be verified: {error}"
        finally:
            profile.unlink(missing_ok=True)
    return True, "Permission rules enforced; profiles in {}".format(launch["destination"])


def create_profile(destination, workspace):
    role = workspace / "role.md"
    role.write_text("Health check profile; never used for a model run.\n")
    access = dict(roots=[workspace], readable=[], writable=[])
    return make_profile(role, destination, workspace.name, access)
