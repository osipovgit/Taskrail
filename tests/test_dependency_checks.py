"""Historical baselines stay lossless, scoped to dependencies and separate from current gates."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import (
    check_artifacts,
    check_results,
    dependency_checks,
    execution_wait,
    report_sources,
)
from taskrail.core.files import atomic_json
from taskrail.interactions import local_journal


class DependencyChecksTests(unittest.TestCase):
    def test_selected_remote_and_configured_reports_keep_their_own_recorded_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            outcome = dict(stdout="large output\n" * 300, stderr="", exit_code=0)
            ticket = dict(id="example.ticket", results=[outcome])
            remote = execution_wait.save_snapshot(run, ticket)
            check = run / "00-input/checks/example.ticket.json"
            check.parent.mkdir()
            atomic_json(check, dict(execution=check_artifacts.stored_output(check, outcome)))
            remote_output = remote.with_suffix(".1-stdout.txt")
            check_output = check.with_suffix(".stdout.txt")
            selected = report_sources.selected(run, [str(remote_output), str(check_output)], ())
            self.assertEqual(
                set(selected),
                {remote, remote_output, check, check_output, check.with_suffix(".stderr.txt")},
            )
            orphan = check.with_suffix(".console.txt")
            orphan.write_text("not produced")
            with self.assertRaisesRegex(ValueError, "not recorded"):
                report_sources.selected(run, [str(orphan)], ())

    def test_only_finished_direct_dependency_commands_travel_with_the_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            child = base / "child"
            (child / "00-input").mkdir(parents=True)
            source = base / "approved"
            source.mkdir()
            parent = dict(run=base / "parent", epic=dict(tasks=dict(T1="approved", T2="sibling")))
            output = "long json line " * 2000 + "\nlast line\n"
            action = dict(
                id="a1",
                stage="01-implement",
                request=dict(cwd="/checkout", argv=["lint", "."]),
                status="FAILED",
                outcome=dict(stdout=output, stderr="lint failed\n", exit_code=2),
                source_snapshot={"project/a": "sha"},
            )
            atomic_json(
                source / local_journal.NAME,
                [
                    action,
                    dict(action, id="a2"),
                    dict(action, status="UNKNOWN"),
                    dict(action, effects=["project/a"]),
                ],
            )
            spec = dependency_checks.capture(child, parent, dict(depends_on=["T1"]))
            path = Path(dependency_checks.index(child, spec))
            rows = json.loads(path.read_text())
            self.assertEqual([entry["action_id"] for entry in rows], ["a1", "a2"])
            self.assertEqual(rows[0]["exit_code"], 2)
            self.assertEqual({entry["task"] for entry in rows}, {"T1"})
            stdout = path.parent / rows[0]["stdout"]
            self.assertEqual(stdout.read_text(), output)
            self.assertFalse(check_results.trusted(child))
            stdout.write_text("changed")
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                dependency_checks.index(child, spec)
