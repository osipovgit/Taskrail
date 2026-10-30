"""Private release, host paths and privilege stubs for deployment tests."""

import os
import re
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SYSTEM_PATHS = (
    "/etc/systemd/system/taskrail-executor.service",
    "/usr/local/bin/taskrail-executor-approve",
    "/run/taskrail-executor-maintenance.lock",
    "/opt/taskrail-executor",
    "/etc/taskrail-executor",
    "/var/lib/taskrail-executor",
    "/run/taskrail-executor",
)


class DeploymentFixture:
    """Never expose a test installer to the host's executor or privilege commands."""

    def __init__(self, home):
        self.home = home
        self.system = home / "system"
        self.release = home / "release"
        self.binaries = home / "deployment-bin"
        self.binaries.mkdir()
        for name in ("sudo", "systemctl", "loginctl", "runuser", "useradd", "usermod", "groupadd"):
            executable = self.binaries / name
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$HOME/privilege.log"\nexit 0\n'
            )
            executable.chmod(0o755)
        opencode = self.binaries / "opencode"
        opencode.write_text(
            '#!/bin/sh\nif [ "$#" -eq 1 ] && [ "$1" = --version ]; then\n'
            "    printf '1.19.3\\n'\n    exit 0\nfi\n"
            "printf 'Deployment fixture must not call a model\\n' >&2\nexit 1\n"
        )
        opencode.chmod(0o755)

    def environment(self, environment):
        return dict(
            environment,
            PATH=str(self.binaries) + os.pathsep + environment["PATH"],
            OPENCODE_CONFIG_DIR=str(self.home / ".config/opencode"),
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_DATA_HOME=str(self.home / ".local/share"),
            XDG_STATE_HOME=str(self.home / ".local/state"),
            XDG_CACHE_HOME=str(self.home / ".cache"),
        )

    def source(self):
        if not self.release.exists():
            self.release.mkdir()
            for name in ("taskrail", "deploy", "docs"):
                shutil.copytree(
                    BASE / name,
                    self.release / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            for name in ("pyproject.toml", "README.md", "LICENSE"):
                shutil.copyfile(BASE / name, self.release / name)
            for script in (self.release / "deploy").glob("*.sh"):
                pattern = "|".join(map(re.escape, SYSTEM_PATHS))
                text = re.sub(
                    pattern,
                    lambda match: str(self.system / match.group().removeprefix("/")),
                    script.read_text(),
                )
                script.write_text(text)
        return self.release
