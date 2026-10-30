"""Missing required local tools stop before model work without granting host actions."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from live_fixture import LiveFixture

from taskrail.application import local_preflight
from taskrail.application.checkpoints import resume_available
from taskrail.infrastructure import sandbox


class LocalPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.workflow = SimpleNamespace(
            config=dict(roots={"p": root}, verify_commands=[]),
            state=dict(requirements=[]),
            run=root,
        )

    def command(self, program):
        self.workflow.config["verify_commands"] = [
            dict(cwd=str(self.workflow.run), argv=[program, "--version"], timeout_seconds=5)
        ]

    def test_missing_tool_stops_without_executing_or_asking(self):
        self.command("taskrail-nonexistent-fixture-tool")
        with (
            patch("taskrail.interactions.approvals.wait") as asked,
            self.assertRaisesRegex(ValueError, "Required local tools are unavailable"),
        ):
            local_preflight.prepare(self.workflow)
        asked.assert_not_called()
        report = json.loads((self.workflow.run / "local-preflight.json").read_text())
        self.assertIsNone(report["tools"][0]["executable"])

    def test_installed_tool_records_host_approval_fallback_without_asking(self):
        self.command(sys.executable)
        with (
            patch.object(sandbox, "mode", return_value=None),
            patch("taskrail.interactions.approvals.wait") as asked,
        ):
            local_preflight.prepare(self.workflow)
        asked.assert_not_called()
        report = self.workflow.state[local_preflight.KEY]
        self.assertIsNone(report["sandbox"])
        self.assertIn("waits for approval", report["explanation"])
        self.assertEqual(report["tools"][0]["executable"], sys.executable)

    def test_remote_delivery_and_unbound_research_do_not_require_local_tools(self):
        self.command("taskrail-nonexistent-fixture-tool")
        for extra in (dict(phase="server"), dict(read_only=True)):
            with self.subTest(extra=extra):
                self.workflow.config.update(extra)
                local_preflight.prepare(self.workflow)
                self.assertEqual(self.workflow.state[local_preflight.KEY]["tools"], [])
                for name in extra:
                    self.workflow.config.pop(name)


class PreflightWorkflowTests(LiveFixture, unittest.TestCase):
    def test_missing_mandatory_tool_is_reported_before_any_model_attempt(self):
        self.real_repository()
        run, status, state = self.run_mode(
            worktree_base=str(self.base / "worktrees"),
            verify_commands=[
                dict(cwd=str(self.root), argv=["taskrail-missing-tool"], timeout_seconds=5)
            ],
        )
        self.assertEqual(status, "BLOCKED")
        self.assertIn("Required local tools are unavailable", state["summary"])
        self.assertFalse(state["attempts"])
        self.assertTrue((run / "local-preflight.json").is_file())
        self.assertTrue(resume_available(run, state)[0])
