"""Disposable workflow storage and current-format server artifacts for tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from taskrail.application.run_store import FORMAT
from taskrail.core.release import RELEASE_ID


def current_run(fields):
    """Explicit fixtures can override metadata to exercise rejected formats."""
    return {"run_format": FORMAT, "release_identity": RELEASE_ID, **fields}


def workflow_workspace(case):
    """Keep the application's default worktrees, locks and provider data inside the fixture."""
    temporary = tempfile.TemporaryDirectory()
    case.addCleanup(temporary.cleanup)
    base = Path(temporary.name)
    home = base / "home"
    home.mkdir()
    environment = patch.dict(os.environ, HOME=str(home))
    environment.start()
    case.addCleanup(environment.stop)
    for name in (
        "TASKRAIL_SETTINGS",
        "OPENCODE_CONFIG_DIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    ):
        os.environ.pop(name, None)
    return base
