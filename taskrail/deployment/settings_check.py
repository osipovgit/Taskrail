"""Validate installation settings with the same parsers used before a workflow."""

from pathlib import Path

from taskrail.application import check_recipes, task_config, worktree_isolation
from taskrail.core import protected_paths
from taskrail.infrastructure.opencode_settings import launch_settings


def validate(options, base, roles):
    """Check values and complete role contracts without starting a provider session."""
    launch_settings(options, base)
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
