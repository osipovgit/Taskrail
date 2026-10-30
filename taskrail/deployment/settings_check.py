"""Validate installation settings with the same parsers used before a workflow."""

import json
from pathlib import Path

from taskrail.application import check_recipes, task_config, worktree_isolation
from taskrail.core import protected_paths
from taskrail.infrastructure.agent_sync import launch_settings


def validate(options, base, roles):
    """Check values and complete role contracts without starting a provider session."""
    if not isinstance(options, dict):
        raise ValueError("Settings must be a JSON object")
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
    worktree_isolation.isolation_settings({}, options, base / "runs")
    for key in ("agent_directory", "run_base"):
        Path(options.get(key, base)).expanduser()


def validate_roles(source):
    """All three role files must declare the supported instruction contract."""
    task_config.agent_source(dict(agent_source=str(source)), source.parent)


def preflight(installation, arguments):
    """Validate current or first-install configuration against the incoming role contract."""
    for path in (arguments.config, installation.target, arguments.config / "service.env"):
        if path.is_symlink():
            raise ValueError(f"Installation configuration must not be redirected: {path}")
    if arguments.fresh or not installation.target.exists():
        options = installation.first_settings(arguments.supplied, copy_roles=False)
        roles = imported_roles(arguments)
    else:
        options = json.loads(installation.target.read_text())
        roles = Path(options.get("agent_source", installation.bundled_agents)).expanduser()
        roles = arguments.config / roles
    if arguments.agents == "bundled" or str(roles) == installation.bundled_agents:
        roles = arguments.source / "taskrail/agents"
    validate(options, arguments.config, roles)


def imported_roles(arguments):
    """Validate imported role bytes at their source before their destination exists."""
    if arguments.supplied:
        source = Path(arguments.supplied).expanduser().resolve()
        roles = json.loads(source.read_text()).get("agent_source")
        if roles is not None:
            return source.parent / Path(roles).expanduser()
    return arguments.source / "taskrail/agents"
