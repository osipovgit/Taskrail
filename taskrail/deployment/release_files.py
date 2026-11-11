"""Files shipped from a trusted source tree to the application or isolated executor."""

import shutil
import sys
from pathlib import Path

from taskrail.core.release import regular, runtime_files

EXECUTOR = (
    "__init__.py",
    "core/__init__.py",
    "core/files.py",
    "core/schema.py",
    "core/schema_fields.py",
    "core/result-schemas.json",
    "deployment/__init__.py",
    "deployment/executor_check.py",
    "executor/__init__.py",
    "executor/__main__.py",
    "executor/action_schema.py",
    "executor/approval.py",
    "executor/client.py",
    "executor/hosts.py",
    "executor/jenkins_build.py",
    "executor/jenkins_config.py",
    "executor/jenkins_http.py",
    "executor/jenkins_reads.py",
    "executor/jenkins_schema.py",
    "executor/protocol.py",
    "executor/service.py",
    "executor/store.py",
    "executor/streams.py",
    "executor/tickets.py",
    "executor/transport.py",
    "executor/worker.py",
)
EXECUTOR_ASSETS = (
    "executor-hosts.example.json",
    "executor-jenkins.example.json",
    "executor-service",
    "ssh-askpass",
    "taskrail-executor-approve",
    "taskrail-executor.service",
)
DEPLOY = (
    *EXECUTOR_ASSETS,
    "executor-maintenance.sh",
    "fresh.sh",
    "install-executor.sh",
    "install-locks.sh",
    "install.sh",
    "options.sh",
    "reset-executor.sh",
    "taskrail",
    "taskrail.service",
)


def release_files(source, component):
    """Select files needed to run and maintain the chosen service."""
    package = source / "taskrail"
    if component == "executor":
        yield from regular(package / name for name in EXECUTOR)
        yield from regular(source / "deploy" / name for name in EXECUTOR_ASSETS)
    elif component == "application":
        yield from runtime_files(package)
        deployment = (source / "deploy" / name for name in DEPLOY)
        yield from regular((*deployment, source / "README.md", source / "LICENSE"))
    else:
        raise ValueError(f"Unknown release component: {component}")


def main():
    """Populate an empty private staging directory from an extracted release."""
    component = sys.argv[1]
    source, destination = map(Path, sys.argv[2:])
    source = source.resolve()
    for path in release_files(source, component):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)
