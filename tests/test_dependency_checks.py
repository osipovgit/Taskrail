"""Historical baselines stay lossless, scoped to dependencies and separate from current gates."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import check_results, dependency_checks
from taskrail.core.files import atomic_json
from taskrail.interactions import local_journal


class DependencyChecksTests(unittest.TestCase):
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
