"""Validate installation settings with the same parsers used before a workflow."""

import json
import sys
from pathlib import Path

from taskrail import onboarding
from taskrail.application import check_recipes, task_config, worktree_isolation
from taskrail.core import protected_paths
from taskrail.core.files import atomic_write
from taskrail.infrastructure.opencode_settings import profile_settings


def validate(options, base, roles):
    """Check values and complete role contracts without starting a provider session."""
    profile_settings(options, base)
    task_config.limits(options)
    task_config.parse_commands(options)
    check_recipes.parse_catalog(options)
    protected_paths.configured(options)
    validate_storage(options, base)
    validate_roles(roles)


def validate_storage(options, base):
    """Paths use the runtime's validators and must be parseable before installation."""
    task_config.permission_worktree(options)
    worktree_isolation.isolation_settings({}, options)
    for key in ("agent_directory", "run_base"):
        Path(options.get(key, base)).expanduser()


def validate_roles(source):
    """Every bundled role must declare the supported instruction contract."""
    task_config.agent_source(dict(agent_source=str(source)), source.parent)


def main():
    """Check the candidate configuration under the service environment, before shutdown."""
    config, prepared = map(Path, sys.argv[1:3])
    current = config / "settings.json"
    candidate = prepared / current.name
    if not candidate.is_file():
        candidate = current
    digest = onboarding.check_connection(
        json.loads(candidate.read_text()),
        config,
        force=bool(sys.argv[3]) or not current.is_file(),
    )
    if digest is not None:
        atomic_write(prepared / onboarding.CHECK_MARKER, f"{digest}\n".encode())
