"""Authenticated Follow-up launches fork the entire preceding result, not its checkout."""

import json
import unittest
from pathlib import Path

from live_fixture import LiveFixture

from taskrail.application import run_setup, task_branch
from taskrail.application.live import execute_task
from taskrail.git import process
from taskrail.web.history import task_draft
from taskrail.web.run_activity import run_sources


class FollowupWorkflowTests(LiveFixture, unittest.TestCase):
    def test_new_branch_includes_commits_and_both_pending_layers_without_changing_parent(self):
        parent, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW")
        previous = Path(state["roots"]["project"])
        (previous / "hello.py").write_text("# staged context\ndef hello():\n    return 2\n")
        process.checked(previous, ["add", "hello.py"])
        (previous / "hello.py").write_text("# unstaged context\ndef hello():\n    return 2\n")
        (previous / "pending.bin").write_bytes(b"\x00pending\xff")
        (previous / "unrelated.txt").write_text("staged notes\n")
        process.checked(previous, ["add", "--", "unrelated.txt"])
        (previous / "unrelated.txt").write_text("working notes\n")
        original_index = process.checked(previous, ["ls-files", "--stage", "-z"])
        original_status = process.checked(previous, ["status", "--porcelain", "-z"])
        head = process.checked(previous, ["rev-parse", "HEAD"]).strip()
        folder = self.base / ".submissions/followup"
        folder.mkdir(parents=True)
        task = folder / "task.md"
        task.write_text(
            "```taskrail-task\n" + json.dumps(dict(roots=state["roots"])) + "\n```\nReturn 2"
        )
        launch = dict(
            launch_id="followup",
            id="followup",
            resume=False,
            submission_mode="followup",
            execution_parent=parent.name,
        )
        (folder / "launch.json").write_text(json.dumps(launch))
        self.configure_mode("review-timeout", transport_retries=0)
        child, status = execute_task(task, self.settings, run_dir=self.base / "followup")
        interrupted = json.loads((child / "run.json").read_text())
        self.assertEqual(status, "TIMEOUT", interrupted.get("summary"))
        current = Path(interrupted["roots"]["project"])
        self.assertEqual(process.checked(current, ["rev-parse", "HEAD"]).strip(), head)
        self.assertEqual(process.checked(current, ["ls-files", "--stage", "-z"]), original_index)
        preimage = child / interrupted["preimages"]["project/hello.py"]
        self.assertEqual(preimage.read_text(), process.checked(previous, ["show", "HEAD:hello.py"]))
        patch = (child / "changes.diff").read_text()
        self.assertIn("+# unstaged context", patch)
        self.assertNotIn("working notes", patch)
        self.configure_mode()
        _, status = execute_task(task, self.settings, run_dir=child, resume=True)

        after = json.loads((child / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", after.get("summary"))
        current = Path(after["roots"]["project"])
        self.assertNotEqual(current, previous)
        self.assertEqual(after["worktrees"]["project"]["base"], head)
        self.assertEqual(
            process.checked(current, ["branch", "--show-current"]).strip(), "taskrail/followup"
        )
        self.assertEqual(process.checked(previous, ["ls-files", "--stage", "-z"]), original_index)
        self.assertEqual(
            process.checked(current, ["diff", "--name-only", head, "HEAD"]), "hello.py\n"
        )
        self.assertEqual(
            process.checked(current, ["show", "HEAD:hello.py"]), (current / "hello.py").read_text()
        )
        self.assertEqual(process.checked(current, ["show", ":unrelated.txt"]), "staged notes\n")
        self.assertEqual((current / "unrelated.txt").read_text(), "working notes\n")
        self.assertEqual(after["changed_files"], ["project/hello.py"])
        self.assertEqual(
            process.checked(previous, ["status", "--porcelain", "-z"]), original_status
        )
        self.assertEqual((current / "hello.py").read_bytes(), (previous / "hello.py").read_bytes())
        self.assertEqual((current / "pending.bin").read_bytes(), b"\x00pending\xff")
        self.assertEqual(task_draft(child)["roots"][0]["path"], str(self.original_root))

        planner = next(stage for stage in after["stages"] if stage["stage"] == "planner")
        request = (child / planner["directory"] / "request.md").read_text()
        mapping = json.loads(request.split("Context:\n", 1)[1])["workspace_paths"]
        self.assertEqual(mapping[str(previous)], str(current))
        self.assertEqual(mapping[str(self.original_root)], str(current))

        previous.rename(self.base / "archived-parent-checkout")
        self.assertTrue(task_branch.detect({"project": current}, after["worktrees"]))
        resumed_sources = run_setup.source_roots({}, dict(resume=True, run_dir=child))
        self.assertEqual(resumed_sources, [str(self.original_root)])
        self.assertEqual(run_sources(child), [str(self.original_root)])
