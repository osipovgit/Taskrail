"""A task on a temporary repository, run through the workflow with the fake opencode."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

from git_fixture import repository
from run_fixture import workflow_workspace

from taskrail.application.live import execute_task

BASE = Path(__file__).resolve().parents[1]


class LiveFixture:
    """setUp, configure_mode and run_mode of workflow tests."""

    def setUp(self):
        self.base = workflow_workspace(self)
        self.root = self.base / "repo"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        (self.root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.root / "hello.py").write_text("# user comment\ndef hello():\n    return 1\n")
        (self.root / "unrelated.txt").write_text("user dirty work\n")
        self.task = self.base / "task.md"
        self.task.write_text(
            "```taskrail-task\n"
            + json.dumps({"roots": {"project": str(self.root)}})
            + "\n```\nReturn 2"
        )
        self.original_root = self.root
        self.real_repository()
        self.settings = self.base / "settings.json"
        self.profiles = self.base / "profiles"

    def configure_mode(self, mode="ok", **overrides):
        settings = dict(
            worktree_base=str(self.base / "worktrees"),
            command=[
                sys.executable,
                str(BASE / "tests/fake_live.py"),
                "--profiles",
                str(self.profiles),
                "--mode",
                mode,
            ],
            agent_source=str(getattr(self, "source", BASE / "taskrail/agents")),
            agent_directory=str(self.profiles),
            timeout_seconds=1
            if mode
            in (
                "writer-timeout",
                "timeout-then-invalid",
                "timeout-evidence",
                "review-timeout",
                "planner-timeout",
            )
            else 5,
        )
        settings.update(overrides)
        self.settings.write_text(json.dumps(settings))

    def run_mode(self, mode="ok", **overrides):
        self.configure_mode(mode, **overrides)
        with (
            patch(
                "taskrail.interactions.approvals.wait",
                return_value=dict(decision="deny", alternative="Use permitted source paths"),
            ),
            patch("taskrail.interactions.turn_recovery.WAITS", (0, 0, 0)),
        ):
            run, status = execute_task(self.task, self.settings, run_dir=self.base / "result")
        state = json.loads((run / "run.json").read_text())
        self.root = Path(state["roots"]["project"])
        return run, status, state

    def real_repository(self):
        """Commit fixture setup before adding intentionally pending original edits."""
        return repository(self.root)
