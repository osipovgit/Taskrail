"""A delivered executor turn and a newly requested observation have distinct identities."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from taskrail.application import source_tree
from taskrail.infrastructure.event_summary import parse_events
from taskrail.interactions import local_journal, request_routes
from taskrail.interactions.actions import Actions
from taskrail.interactions.session import StageSession


class ExecutorDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name)
        self.folder = self.run / "01-plan"
        self.folder.mkdir()
        self.root = self.run / "project"
        self.root.mkdir()
        self.source = self.root / "Main.java"
        self.source.write_text("class Main {}\n")
        roots = {"project": self.root}
        self.git = {"project/HEAD": "one"}
        self.environment = dict(
            run=self.run,
            roots=roots,
            expected=source_tree.snapshot(roots),
            scan=lambda: source_tree.snapshot(roots),
            git_before=dict(self.git),
            git_metadata=lambda _: dict(self.git),
        )
        self.record = dict(stage="planner", role="planner", timeout_seconds=60)
        self.payload = dict(
            status="LOCAL_REQUEST",
            schema_version=1,
            cwd=str(self.root),
            argv=["wc", "-l", "Main.java"],
            reason="Count the source lines",
        )

    def actions(self):
        return Actions(
            StageSession(
                (self.folder, self.record),
                {"stages": [self.record], "attempts": []},
                self.environment,
                {},
            )
        )

    def outcome(self, message, payload):
        event = dict(
            type="text", sessionID="ses", part=dict(messageID=message, text=json.dumps(payload))
        )
        finish = dict(
            type="step_finish", sessionID="ses", part=dict(messageID=message, reason="stop")
        )
        path = self.folder / "native-turn.jsonl"
        path.write_text("\n".join(map(json.dumps, [event, finish])))
        return dict(parse_events(path), status="OK")

    def test_redelivery_and_format_repair_reuse_a_real_content_read(self):
        with patch("taskrail.infrastructure.sandbox.mode", return_value=None):
            first = self.actions().route(self.outcome("one", self.payload))
            self.assertIn("1 Main.java", first)
            self.assertEqual(self.actions().route(self.outcome("one", self.payload)), first)
            (self.run / "plan.md").write_text("Corrected the requirement row.")
            reused = self.actions().route(self.outcome("two", self.payload))
            self.assertIn("existing receipt", reused)
            self.assertEqual(len(list((self.run / "00-input/local").glob("*.json"))), 1)
            self.source.write_text("class Main {\n}\n")
            self.environment["expected"] = self.environment["scan"]()
            fresh = self.actions().route(self.outcome("three", self.payload))
            self.assertIn("2 Main.java", fresh)
            self.git["project/HEAD"] = "two"
            self.environment["git_before"] = dict(self.git)
            self.assertIn("2 Main.java", self.actions().route(self.outcome("four", self.payload)))
            new_check = dict(self.payload, reason="Confirm current contents before delivery")
            self.assertIn("2 Main.java", self.actions().route(self.outcome("five", new_check)))
            listing = dict(self.payload, argv=["ls", "-l"])
            for number in ("six", "seven"):
                self.assertIn("Main.java", self.actions().route(self.outcome(number, listing)))
        self.assertEqual(len(local_journal.records(self.run)), 6)

    def test_each_executor_reserves_its_message_before_dispatch_even_on_interruption(self):
        requests = [
            self.payload,
            dict(
                schema_version=1,
                status="GIT_REQUEST",
                root=str(self.root),
                argv=["status"],
                reason="Inspect",
            ),
            dict(
                schema_version=1,
                status="ACTION_REQUEST",
                action=dict(
                    targets=["fixture"],
                    script="uptime\n",
                    files={},
                    reason="Inspect",
                    timeout_seconds=30,
                ),
            ),
            dict(
                schema_version=1,
                status="JENKINS_REQUEST",
                jenkins=dict(operation="build", server="example", job="test", parameters={}),
            ),
        ]
        for payload in requests:
            kind = payload["status"]
            with self.subTest(kind=kind):
                execute = Mock(side_effect=[KeyboardInterrupt(), "completed"])
                with patch.object(request_routes, "ROUTES", {kind: execute}):
                    with self.assertRaises(KeyboardInterrupt):
                        self.actions().route(self.outcome(kind, payload))
                    self.assertIn("uncertain", self.actions().route(self.outcome(kind, payload)))
                    fresh = self.outcome(kind + "-new", payload)
                    self.assertEqual(self.actions().route(fresh), "completed")
                    self.assertEqual(self.actions().route(fresh), "completed")
                    self.assertEqual(execute.call_count, 2)

    def test_ambiguous_identity_and_conflicting_payload_cannot_execute(self):
        execute = Mock(return_value="receipt")
        with patch.object(request_routes, "ROUTES", {"LOCAL_REQUEST": execute}):
            ready = self.outcome("one", self.payload)
            for invalid in (
                dict(sessions=[]),
                dict(sessions=["a", "b"]),
                dict(final_message_id=None),
            ):
                self.assertIn("No action started", self.actions().route(dict(ready, **invalid)))
            self.assertEqual(self.actions().route(ready), "receipt")
            conflict = self.outcome("one", dict(self.payload, argv=["ls"]))
            self.assertIsNone(self.actions().route(conflict))
            self.assertEqual(conflict["status"], "SESSION_ERROR")
        execute.assert_called_once()
