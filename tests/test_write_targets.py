"""Native write recovery recognizes aliases without expanding an approved file's scope."""

import tempfile
import unittest
from pathlib import Path

from taskrail.application import plan_write
from taskrail.infrastructure import write_targets


class WriteTargetTests(unittest.TestCase):
    def test_plan_feedback_uses_canonical_target_for_aliases_and_preserves_raw_failures(self):
        run = Path("/run/task")
        target = str(run / "plan.md")
        alias = "/run/task/nested/../plan.md"
        for supplied, reported in ((alias, alias), (target, alias), (alias, target)):
            for prefix in ("", "Error: "):
                with self.subTest(supplied=supplied, reported=reported, prefix=prefix):
                    failure = dict(
                        tool="edit",
                        input=dict(filePath=supplied),
                        error=f"{prefix}You must read file {reported} before overwriting it. Use the Read tool first",
                    )
                    outcome = dict(
                        status="TOOL_ERROR", tool_errors=[failure], errors=[failure["error"]]
                    )
                    feedback = plan_write.read_before_write(outcome, run)
                    self.assertIn(target, feedback)
                    self.assertNotIn("../", feedback)
                    self.assertEqual(failure["input"]["filePath"], supplied)
                    for extra in (
                        dict(permission=True),
                        dict(exit_code=1),
                        dict(status="SCOPE_VIOLATION"),
                        dict(errors=[failure["error"], "unknown error"]),
                    ):
                        self.assertIsNone(plan_write.read_before_write(dict(outcome, **extra), run))

    def test_alias_matching_does_not_follow_symlinks_to_another_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            run = base / "run"
            run.mkdir()
            target = run / "plan.md"
            target.write_text("approved plan\n")
            outside = base / "outside" / "nested"
            outside.mkdir(parents=True)
            (outside.parent / "plan.md").write_text("other plan\n")
            (run / "link").symlink_to(outside, target_is_directory=True)
            alias = str(run / "link" / ".." / "plan.md")
            self.assertNotEqual(Path(alias).resolve(), target)
            self.assertIsNone(write_targets.approved(alias, (str(target),)))
            (run / "alias.md").symlink_to(target)
            self.assertIsNone(write_targets.approved(str(run / "alias.md"), (str(target),)))
            (run / "loop").symlink_to(run / "loop")
            self.assertIsNone(write_targets.approved(str(run / "loop/../plan.md"), (str(target),)))

    def test_resolved_warnings_do_not_prevent_repairing_a_remaining_plan_rejection(self):
        run = Path("/run/task")
        alias = "/run/task/nested/../plan.md"
        rejected = dict(
            tool="edit",
            input=dict(filePath=alias),
            error=f"You must read file {alias} before overwriting it. Use the Read tool first",
        )
        resolved = dict(rejected, resolution="Actual read and successful write observed")
        outcome = dict(
            status="TOOL_ERROR",
            errors=[rejected["error"]],
            tool_errors=[resolved, rejected],
        )
        self.assertIn(str(run / "plan.md"), plan_write.read_before_write(outcome, run))
        outcome["tool_errors"].insert(
            0, dict(error="File not found", resolution="Read changed nothing")
        )
        self.assertIsNotNone(plan_write.read_before_write(outcome, run))
        outcome["errors"].append("unexplained failure")
        self.assertIsNone(plan_write.read_before_write(outcome, run))

    def test_paths_outside_exact_targets_and_unknown_messages_are_not_recoverable(self):
        target = "/run/task/plan.md"
        for path in (None, {}, "plan.md", "../task/plan.md", "/run/task2/plan.md", target + "\0"):
            with self.subTest(path=path):
                self.assertIsNone(write_targets.approved(path, (target,)))
        failure = dict(tool="edit", input=dict(filePath=target))
        for message in (
            "Must read before writing",
            "PermissionDeniedError: must read first",
            "You must read file /outside/plan.md before overwriting it. Use the Read tool first",
            f"You must read file {target} before overwriting it. Use the Read tool first Extra error",
        ):
            with self.subTest(message=message):
                self.assertFalse(write_targets.unread(dict(failure, error=message), target))


if __name__ == "__main__":
    unittest.main()
