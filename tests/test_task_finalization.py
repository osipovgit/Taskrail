"""Automatic task commits preserve ownership and journal every uncertain mutation."""

import json
import random
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from run_fixture import current_run

from taskrail.application import (
    attempt_session,
    changes,
    implementation_submission,
    inherited_preimages,
    prior_git,
    resume_inputs,
    task_branch,
    task_commit,
    worktree_isolation,
)
from taskrail.application.changes import capture_preimages
from taskrail.application.source_guard import SourceGuard
from taskrail.core.files import atomic_json
from taskrail.git import execution, process, requests, reviewed_commit, transport


class TaskFinalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.run = self.base / "run"
        (self.run / "00-input").mkdir(parents=True)
        atomic_json(self.run / "implementation.json", dict(summary="Change the output"))
        self.roots = {}
        self.records = {}
        self.add_repository("project")

    def add_repository(self, alias):
        source = self.base / f"source-{alias}"
        source.mkdir()
        process.checked(source, ["init", "-b", "main"])
        process.checked(source, ["config", "user.name", "Fixture"])
        process.checked(source, ["config", "user.email", "fixture@example.invalid"])
        (source / "target.txt").write_text("before\n")
        (source / "unrelated.txt").write_text("user content\n")
        (source / ".gitattributes").write_text("target.txt filter=probe\n")
        process.checked(source, ["add", "--all"])
        process.checked(source, ["commit", "-m", "Initial"])
        root = self.base / f"worktree-{alias}"
        self.records[alias] = worktree_isolation.create(source, root, alias)
        self.roots[alias] = root
        return root

    def workflow(self):
        guard = SourceGuard(self.roots)
        guard.capture()
        atomic_json(self.run / "00-input/manifest.json", guard.before)
        changes = [f"{alias}/target.txt" for alias in self.roots]
        originals = {}
        capture_preimages(self.run, self.roots, changes, originals)
        for root in self.roots.values():
            (root / "target.txt").write_text("reviewed output\n")
        guard.accept(changes)
        state = dict(
            status="READY_FOR_REVIEW",
            changed_files=changes,
            attempts=[],
            preimages=originals,
            results=dict(implementation="implementation.json"),
        )
        implementation_submission.publish(self.run / "01-implement", state, "# Change the output")
        return SimpleNamespace(
            run=self.run,
            config=dict(task_branch=True, roots=self.roots, worktrees=self.records, phase="task"),
            state=current_run(state),
            guard=guard,
            checkpoint=lambda: None,
        )

    def test_a_successful_commit_has_a_controlled_content_receipt(self):
        root = self.roots["project"]
        process.checked(root, ["config", "commit.cleanup", "strip"])
        workflow = self.workflow()
        task_commit.commit(workflow)
        self.assertEqual(workflow.state["status"], "READY_FOR_REVIEW")
        preview = self.run / workflow.state["implementation_submission"]["path"]
        body = process.raw(root, ["cat-file", "commit", "HEAD"]).stdout.split(b"\n\n", 1)[1]
        self.assertEqual(body, preview.read_bytes())
        entries = requests.history(self.run)
        self.assertEqual([entry["status"] for entry in entries], ["SUCCEEDED", "SUCCEEDED"])
        receipt = entries[-1]["source_baseline"]
        self.assertEqual(workflow.state["commits"][0]["commit"], receipt["head"])
        self.assertEqual(set(receipt["files"]), {str(self.roots["project"] / "target.txt")})
        workflow.guard.verify("Finalization must preserve reviewed source")

    def test_changed_submission_cannot_be_committed_after_approval(self):
        workflow = self.workflow()
        note = self.run / workflow.state["implementation_submission"]["path"]
        note.write_text("different message")
        with self.assertRaisesRegex(ValueError, "submission changed"):
            task_commit.commit(workflow)
        self.assertEqual(requests.history(self.run), [])

    def test_followup_reviews_and_commits_binary_mode_and_already_staged_deletion(self):
        root = self.roots["project"]
        script = root / "run.sh"
        script.write_bytes(b"exit 0\n")
        process.checked(root, ["add", "--", "run.sh"])
        process.checked(root, ["commit", "-m", "Script baseline"])
        original_head = process.checked(root, ["rev-parse", "HEAD"]).strip()
        selected = ["run.sh", "target.txt", "new.bin", "empty.txt"]
        record = self.records["project"]
        record.update(original_source=record["source"], carried_files=[*selected, "unrelated.txt"])
        script.chmod(0o755)
        (root / "target.txt").unlink()
        process.checked(root, ["add", "--", "target.txt"])
        binary = random.Random(0).randbytes(transport.OUTPUT_LIMIT + 1)
        (root / "new.bin").write_bytes(binary)
        (root / "empty.txt").touch()
        (root / "unrelated.txt").write_text("staged notes")
        process.checked(root, ["add", "--", "unrelated.txt"])
        (root / "unrelated.txt").write_text("working notes")
        guard = SourceGuard(self.roots)
        guard.capture()
        state = current_run(
            dict(
                status="READY_FOR_REVIEW",
                preimages={},
                attempts=[],
                results=dict(implementation="implementation.json"),
            )
        )
        names = [f"project/{name}" for name in selected]
        workflow = SimpleNamespace(
            run=self.run,
            config=dict(roots=self.roots, worktrees=self.records, task_branch=True),
            guard=guard,
            flow=dict(allowed=names),
            state=state,
            checkpoint=lambda: None,
        )
        changes.capture(workflow)
        workflow.writable = lambda: names
        env = attempt_session.session_environment(workflow, None, None)
        head_before = process.checked(root, ["rev-parse", "HEAD"])
        index_before = process.checked(root, ["ls-files", "--stage", "-z"])
        for args in (["add", "--", "new.bin"], ["commit", "-m", "Too early"]):
            entry = dict(request=reviewed_commit.payload(root, args), status="RUNNING")
            execution.execute(entry, [], "implementer", env)
            self.assertEqual(entry["status"], "REJECTED")
            self.assertIn("server stages and commits after independent approval", entry["stderr"])
        self.assertEqual(process.checked(root, ["ls-files", "--stage", "-z"]), index_before)
        self.assertEqual(process.checked(root, ["rev-parse", "HEAD"]), head_before)
        original = self.run / state["preimages"]["project/run.sh"]
        original.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "executable mode"):
            resume_inputs.verify_preimages(self.run, state, guard.before)
        original.chmod(0o600)
        state["changed_files"] = guard.accept(names)
        self.assertEqual(set(state["changed_files"]), set(names))
        changes.write_diff(workflow)
        patch_text = (self.run / "changes.diff").read_text()
        for detail in (
            "GIT binary patch",
            "old mode 100644",
            "new mode 100755",
            "deleted file mode",
            "new file mode",
            "-before",
        ):
            self.assertIn(detail, patch_text)
        self.assertNotIn("unrelated.txt", patch_text)
        self.assertGreater(len(patch_text), transport.OUTPUT_LIMIT)
        implementation_submission.publish(
            self.run / "01-implement", state, "Carry the selected changes"
        )
        task_commit.commit(workflow)
        self.assertEqual(state["status"], "READY_FOR_REVIEW", state.get("summary"))
        committed = process.checked(
            root, ["diff", "--no-renames", "--name-only", original_head, "HEAD"]
        )
        self.assertEqual(set(committed.splitlines()), set(selected))
        self.assertEqual(process.blob(root, "HEAD:new.bin"), binary)
        self.assertEqual(process.blob(root, "HEAD:empty.txt"), b"")
        self.assertEqual(process.checked(root, ["show", ":unrelated.txt"]), "staged notes")
        self.assertEqual((root / "unrelated.txt").read_text(), "working notes")

    def test_existing_user_index_is_preserved_and_never_committed(self):
        root = self.roots["project"]
        (root / "unrelated.txt").write_text("user staged content\n")
        process.checked(root, ["add", "--", "unrelated.txt"])
        before = process.checked(root, ["diff", "--cached"])
        head = process.checked(root, ["rev-parse", "HEAD"])
        workflow = self.workflow()
        task_commit.commit(workflow)
        self.assertEqual(workflow.state["status"], "COMMIT_FAILED")
        self.assertIn("belong to the user", workflow.state["summary"])
        self.assertEqual(process.checked(root, ["diff", "--cached"]), before)
        self.assertEqual(process.checked(root, ["rev-parse", "HEAD"]), head)

    def test_dirty_original_file_is_not_staged_as_owned_work(self):
        root = self.roots["project"]
        (root / "target.txt").write_text("pre-existing user edit\n")
        workflow = self.workflow()
        task_commit.commit(workflow)
        self.assertEqual(workflow.state["status"], "COMMIT_FAILED")
        self.assertIn("pre-existing user edits", workflow.state["summary"])
        self.assertEqual(process.checked(root, ["diff", "--cached"]), "")

    def test_repository_clean_filters_cannot_execute_during_finalization(self):
        root = self.roots["project"]
        marker = self.base / "filter-executed"
        process.checked(root, ["config", "filter.probe.clean", f"touch {marker}; cat"])
        workflow = self.workflow()
        task_commit.commit(workflow)
        self.assertEqual(workflow.state["status"], "READY_FOR_REVIEW")
        self.assertFalse(marker.exists())
        self.assertEqual(process.checked(root, ["show", "HEAD:target.txt"]), "reviewed output\n")

    def test_branch_prefix_without_a_record_never_grants_task_authority(self):
        self.assertFalse(task_branch.detect(self.roots, {}))
        with self.assertRaisesRegex(ValueError, "identity changed"):
            task_branch.detect(
                self.roots, {"project": dict(self.records["project"], branch="taskrail/other")}
            )
        self.assertTrue(task_branch.detect(self.roots, self.records))

    def test_failed_second_repository_keeps_first_receipt_without_success(self):
        failed_root = self.add_repository("second")
        workflow = self.workflow()
        original = process.invoke

        def fail_commit(root, arguments, settings=()):
            if root == failed_root and arguments[0] == "commit":
                return subprocess.CompletedProcess(arguments, 1, "", "fixture commit failure")
            return original(root, arguments, settings)

        with patch("taskrail.git.process.invoke", side_effect=fail_commit):
            task_commit.commit(workflow)
        self.assertEqual(workflow.state["status"], "COMMIT_FAILED")
        self.assertIn("commit", workflow.state["commits"][0])
        self.assertEqual(workflow.state["commits"][1]["error"], "fixture commit failure")
        saved = json.loads((self.run / "run.json").read_text())
        self.assertEqual(saved["status"], "COMMIT_FAILED")
        self.assertEqual(saved["commits"], workflow.state["commits"])

        previous = self.run
        first_head = workflow.state["commits"][0]["commit"]
        self.run = self.base / "restarted"
        (self.run / "00-input").mkdir(parents=True)
        atomic_json(self.run / "implementation.json", dict(summary="Complete the reviewed task"))
        retry = self.workflow()
        inherited_preimages.inherit(retry, [previous])
        prior_git.inherit(retry, [previous])
        task_commit.commit(retry)
        self.assertEqual(retry.state["status"], "READY_FOR_REVIEW", retry.state.get("summary"))
        self.assertEqual(retry.state["commits"][0]["commit"], first_head)
        self.assertEqual(len(requests.history(self.run)), 5)
        self.assertEqual(requests.history(self.run)[-1]["request"]["argv"][0], "commit")
        self.assertEqual(process.checked(failed_root, ["status", "--porcelain"]), "")

    def test_inherited_original_modes_and_bytes_are_sealed_for_continuation(self):
        workflow = self.workflow()
        atomic_json(self.run / "run.json", current_run(workflow.state))
        previous = self.run
        self.run = self.base / "restarted"
        (self.run / "00-input").mkdir(parents=True)
        retry = self.workflow()
        current = dict(retry.guard.before)
        inherited_preimages.inherit(retry, [previous])
        self.assertEqual(retry.guard.before, workflow.guard.before)
        retry.guard.before = current
        inherited_preimages.restore(retry)
        self.assertEqual(retry.guard.before, workflow.guard.before)
        path = self.run / inherited_preimages.BASELINE_FILE
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "identities changed"):
            inherited_preimages.restore(retry)

    def test_interrupted_successful_commit_cannot_be_replayed_or_inherited(self):
        workflow = self.workflow()
        root = self.roots["project"]
        original = process.invoke

        def interrupt_commit(location, arguments, settings=()):
            outcome = original(location, arguments, settings)
            if arguments[0] == "commit":
                raise KeyboardInterrupt
            return outcome

        with (
            patch("taskrail.git.process.invoke", side_effect=interrupt_commit),
            self.assertRaises(KeyboardInterrupt),
        ):
            task_commit.commit(workflow)
        self.assertEqual(requests.history(self.run)[-1]["status"], "UNKNOWN")
        with self.assertRaisesRegex(ValueError, "uncertain"):
            reviewed_commit.require_settled(self.run)
        head = process.checked(root, ["rev-parse", "HEAD"])
        task_commit.commit(workflow)
        self.assertEqual(workflow.state["status"], "COMMIT_FAILED")
        self.assertEqual(process.checked(root, ["rev-parse", "HEAD"]), head)

    def test_source_drift_during_staging_stops_before_commit(self):
        workflow = self.workflow()
        original = execution.execute

        def drift(entry, previous, role, environment):
            original(entry, previous, role, environment)
            (self.roots["project"] / "unrelated.txt").write_text("outside change\n")

        with patch("taskrail.git.execution.execute", side_effect=drift):
            task_commit.commit(workflow)
        self.assertEqual(workflow.state["status"], "COMMIT_FAILED")
        self.assertEqual([entry["status"] for entry in requests.history(self.run)], ["UNKNOWN"])
        self.assertEqual(
            process.checked(self.roots["project"], ["show", "HEAD:target.txt"]), "before\n"
        )


if __name__ == "__main__":
    unittest.main()
