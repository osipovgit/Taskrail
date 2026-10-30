"""Validate private executor configuration before stopping or replacing its service."""

import sys
from pathlib import Path

from taskrail.executor import hosts, jenkins_config


def regular(path):
    """Existing configuration files must never redirect privileged installation writes."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Executor configuration must use regular files: {path}")


def validate(config, source):
    """Parse existing credentials in place; a fresh inventory uses the bundled example."""
    if config.resolve() != config:
        raise ValueError("Executor configuration directory must not be redirected")
    for name in ("hosts.json", "known_hosts", "jenkins.json"):
        regular(config / name)
    inventory = config / "hosts.json"
    hosts.load(inventory if inventory.exists() else source / "deploy/executor-hosts.example.json")
    jenkins_config.load(config / "jenkins.json")


def main():
    """The installer supplies exact root-owned configuration and prepared package paths."""
    config, source, *directories = map(Path, sys.argv[1:])
    for directory in (config, *directories):
        if directory.resolve() != directory:
            raise ValueError(f"Executor installation directory must not be redirected: {directory}")
    validate(config, source)


if __name__ == "__main__":
    main()
