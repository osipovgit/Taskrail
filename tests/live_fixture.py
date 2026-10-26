"""A task on a temporary repository, run through the workflow with the fake opencode."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from taskrail.application.live import execute_task

BASE = Path(__file__).resolve().parents[1]


class LiveFixture:
    """setUp, configure_mode and run_mode of workflow tests."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
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
        self.settings = self.base / "settings.json"
        self.profiles = self.base / "profiles"

    def configure_mode(self, mode="ok", **overrides):
        settings = dict(
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
        with patch(
            "taskrail.interactions.approvals.wait",
            return_value=dict(decision="deny", alternative="Use permitted source paths"),
        ):
            run, status = execute_task(self.task, self.settings, run_dir=self.base / "result")
        state = json.loads((run / "run.json").read_text())
        return run, status, state

    def real_repository(self):
        """Turn the root into a Git repository with one commit; returns the Git runner."""
        from taskrail.git import process

        (self.root / ".git/HEAD").unlink()
        (self.root / ".git").rmdir()
        process.checked(self.root, ["init", "-b", "main"])
        process.checked(self.root, ["config", "user.name", "Fixture"])
        process.checked(self.root, ["config", "user.email", "fixture@example.invalid"])
        process.checked(self.root, ["add", "."])
        process.checked(self.root, ["commit", "-m", "Initial"])
        return process
