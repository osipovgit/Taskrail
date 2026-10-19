"""Effective run configuration from a task file and server settings."""

import json
import re
from pathlib import Path

from countersign.application import instruction_sources
from countersign.application.task_roots import ROOTS, declared_roots
from countersign.application.verify_settings import parse_commands
from countersign.application.worktree_isolation import isolation_settings
from countersign.core.runtime import DEFAULT_TIMEOUT, run_storage, settings_path
from countersign.infrastructure.agent_sync import launch_settings

HEADER = re.compile(r"(?ms)^```countersign-task\s*\n(.*?)^```\s*$")
ROLES = ("planner", "implementer", "reviewer")
BUNDLED_AGENTS = Path(__file__).resolve().parents[1] / "agents"
VERIFICATION = "verification"
DESIGN = "design"
CHANGE_LINES = 400
CHANGE_FILES = 15
CHECK_LIST = "verification must list runtime acceptance checks as strings"


def configuration(task, settings=None, roots_override=None):
    """Validate the task header, roots, role sources and bounded limits."""
    path = Path(task).expanduser().resolve(strict=True)
    text = path.read_text(encoding="utf-8")
    source = settings_path(settings)
    options = json.loads(source.read_text()) if source.exists() else {}
    meta = task_header(text, options, roots_override)
    return dict(
        launch_settings(options, source.parent),
        **limits(options),
        **isolation_settings(meta, options, run_storage(source)),
        read_only=meta.get("read_only") is True or meta.get(DESIGN) is True,
        design=meta.get(DESIGN) is True,
        task=path,
        task_text=text,
        roots=declared_roots(meta, path),
        source=agent_source(options, source.parent),
        verification=verification(meta),
        permission_worktree=permission_worktree(options),
        verify_commands=parse_commands(options),
        run_base=run_storage(source),
    )


def task_header(text, options, roots_override):
    """At most one fenced JSON header; restored roots replace the declared ones."""
    headers = HEADER.findall(text)
    if len(headers) > 1:
        raise ValueError("Only one countersign-task header is supported")
    meta = json.loads(headers[0]) if headers else {}
    if not isinstance(meta, dict) or not isinstance(options, dict):
        raise ValueError("Task header and settings must be JSON objects")
    if roots_override is not None:
        meta[ROOTS] = roots_override
    return meta


def agent_source(options, base):
    """Every role must exist and declare the supported instruction contract."""
    source = base.joinpath(Path(options.get("agent_source", BUNDLED_AGENTS)).expanduser())
    for role in ROLES:
        role_file = source / f"{role}.md"
        if not role_file.is_file():
            raise ValueError(f"Missing source agent: {role}")
        instruction_sources.validate_role_source(role_file)
    return source.resolve()


def verification(meta):
    """Runtime acceptance checks named by the task; they stay unverified until run."""
    checks = meta.get(VERIFICATION, [])
    if not isinstance(checks, list):
        raise ValueError(CHECK_LIST)
    if not all(isinstance(check, str) for check in checks):
        raise ValueError(CHECK_LIST)
    return checks


def permission_worktree(options):
    """An explicit permission base for opencode builds that report it in logs."""
    worktree = options.get("permission_worktree")
    if worktree is None:
        return None
    path = Path(worktree).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(
            "permission_worktree must be an existing absolute directory from opencode logs"
        )
    return path.resolve()


def limits(options):
    """Clamp numeric settings to their supported ranges."""
    return dict(
        stage_seconds=max(1, int(options.get("stage_timeout_seconds", DEFAULT_TIMEOUT * 4))),
        stage_attempts=max(1, int(options.get("max_stage_attempts", 6))),
        max_observed_tokens=max(0, int(options.get("max_observed_tokens", 0))),
        timeout=max(1, int(options.get("timeout_seconds", DEFAULT_TIMEOUT))),
        max_repairs=max(0, min(5, int(options.get("max_repairs", 3)))),
        read_retries=max(0, min(3, int(options.get("read_retries", 3)))),
        max_change_lines=max(0, int(options.get("max_change_lines", CHANGE_LINES))),
        max_change_files=max(0, int(options.get("max_change_files", CHANGE_FILES))),
    )
