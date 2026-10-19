"""Exercise controlled Git against disposable real repositories, never user projects."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from countersign.application import result_validation
from countersign.application.git_state import git_metadata
from countersign.application.plan_validation import validate_plan
from countersign.application.source_tree import snapshot
from countersign.core import coverage
from countersign.git import dispatch, execution, policy, process, requests
from countersign.interactions.session import StageSession


class GitExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        process.checked(self.root, ["init", "-b", "main"])
        process.checked(self.root, ["config", "user.name", "Test"])
        process.checked(self.root, ["config", "user.email", "test@example.invalid"])
        self.file = self.root / "value.txt"
        for number in range(1, 4):
            self.file.write_text(str(number) + "\n")
            process.checked(self.root, ["add", "value.txt"])
            process.checked(self.root, ["commit", "-m", f"Change {number}"])
        self.run = self.base / "run"
        (self.run / "00-input").mkdir(parents=True)
        self.roots = {"project": self.root}
        baseline = snapshot(self.roots)
        (self.run / "00-input/manifest.json").write_text(json.dumps(baseline))
        self.env = dict(
            roots=self.roots,
            run=self.run,
            allowed_paths=[self.file],
            allowed=["project/value.txt"],
            expected=baseline,
            git_before=git_metadata(self.roots),
            scan=lambda: snapshot(self.roots),
            git_metadata=git_metadata,
            format_only=False,
        )

    def payload(self, argv, root=None):
        return dict(
            schema_version=1,
            status="GIT_REQUEST",
            root=str(root or self.root),
            argv=argv,
            reason="Test task",
        )

    def execute(self, argv, role="planner", previous=()):
        record = dict(request=self.payload(argv), status="RUNNING")
        execution.execute(record, list(previous), role, self.env)
        return record

    def test_history_is_real_and_does_not_mutate_metadata(self):
        before = git_metadata(self.roots)
        record = self.execute(["log", "-3", "--format=%H %s", "--", "."])
        self.assertEqual(record["status"], "SUCCEEDED", record)
        self.assertEqual(len(record["stdout"].splitlines()), 3)
        self.assertIn("Change 3", record["stdout"])
        self.assertEqual(before, git_metadata(self.roots))
        for argv in [
            ["show", "HEAD:value.txt"],
            ["diff", "--stat"],
            ["status", "--short"],
            ["reflog", "-3"],
            ["branch", "--all"],
            ["tag"],
            ["blame", "value.txt"],
        ]:
            self.assertEqual(self.execute(argv, "reviewer")["status"], "SUCCEEDED", argv)

    def test_forbidden_commands_never_reach_subprocess(self):
        forbidden = [
            ["reset", "--hard"],
            ["clean", "-fd"],
            ["rebase", "main"],
            ["commit", "--amend"],
            ["push", "--force", "origin"],
            ["push", "origin", "+HEAD:refs/heads/main"],
            ["push", "origin", "HEAD:refs/heads/main", "--force-with-lease"],
            ["-c", "alias.safe=!git reset --hard", "safe"],
            ["filter-branch", "--all"],
            ["reflog", "expire", "--all"],
            ["reflog", "delete", "HEAD@{0}"],
            ["log", "--output=/tmp/forbidden"],
            ["show", "--textconv", "HEAD:value.txt"],
            ["diff", "--no-index", "/etc/passwd", "value.txt"],
            ["branch", "-f", "main", "HEAD~1"],
            ["update-ref", "refs/heads/main", "HEAD~1"],
            ["replace", "HEAD", "HEAD~1"],
        ]
        with patch("countersign.git.process.invoke") as invoke:
            for argv in forbidden:
                with self.subTest(argv=argv):
                    self.assertEqual(self.execute(argv, "implementer")["status"], "REJECTED")
            invoke.assert_not_called()

    def test_reviewers_cannot_write(self):
        for role in ["planner", "reviewer"]:
            with self.assertRaises(ValueError):
                policy.validate(["add", "--", "value.txt"], role)

    def test_revert_creates_new_commit_without_rewriting_history(self):
        original = process.checked(self.root, ["rev-parse", "HEAD"]).strip()
        record = self.execute(["revert", "--no-edit", original], "implementer")
        self.assertEqual(record["status"], "SUCCEEDED", record)
        self.assertEqual(self.file.read_text(), "2\n")
        self.assertEqual(process.checked(self.root, ["rev-parse", "HEAD^"]).strip(), original)
        self.assertEqual(process.checked(self.root, ["rev-list", "--count", "HEAD"]).strip(), "4")
        with patch("countersign.git.process.invoke") as invoke:
            again = self.execute(["revert", "--no-edit", original], "implementer", [record])
            self.assertEqual(again["status"], "REJECTED")
            invoke.assert_not_called()

    def test_dirty_and_out_of_scope_reverts_are_rejected(self):
        revision = process.checked(self.root, ["rev-parse", "HEAD"]).strip()
        self.env["allowed_paths"] = []
        self.assertEqual(
            self.execute(["revert", "--no-edit", revision], "implementer")["status"], "REJECTED"
        )
        self.env["allowed_paths"] = [self.file]
        self.file.write_text("User work\n")
        self.assertEqual(
            self.execute(["revert", "--no-edit", revision], "implementer")["status"], "REJECTED"
        )
        self.assertEqual(self.file.read_text(), "User work\n")

    def test_controlled_add_commit_and_hooks_disabled(self):
        marker = self.base / "hook-ran"
        hook = self.root / ".git/hooks/pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
        hook.chmod(0o755)
        self.file.write_text("4\n")
        staged = self.execute(["add", "--", "value.txt"], "implementer")
        self.assertEqual(staged["status"], "SUCCEEDED", staged)
        committed = self.execute(["commit", "-m", "Approved task change"], "implementer", [staged])
        self.assertEqual(committed["status"], "SUCCEEDED", committed)
        self.assertFalse(marker.exists())
        self.assertEqual(process.checked(self.root, ["show", "HEAD:value.txt"]), "4\n")

    def test_existing_user_changes_cannot_be_staged(self):
        self.file.write_text("User work\n")
        (self.run / "00-input/manifest.json").write_text(json.dumps(snapshot(self.roots)))
        self.file.write_text("User work plus agent work\n")
        self.assertEqual(
            self.execute(["add", "--", "value.txt"], "implementer")["status"], "REJECTED"
        )
        self.assertEqual(process.checked(self.root, ["diff", "--cached", "--name-only"]), "")

    def test_parent_and_guess_are_rejected(self):
        record = dict(request=self.payload(["log", "-3"], self.root.parent))
        execution.execute(record, [], "planner", self.env)
        self.assertEqual(record["status"], "REJECTED")

    def test_dispatch_persists_evidence_and_checkpoint(self):
        folder = self.run / "01-plan"
        folder.mkdir()
        record = dict(directory=folder.name, role="planner")
        state = dict(attempts=[], stages=[record], roots={"project": str(self.root)})
        (self.run / "checkpoint.json").write_text(
            json.dumps(dict(expected=self.env["expected"], git_before=self.env["git_before"]))
        )
        outcome = dict(
            status="OK",
            final_text="Now I'll inspect the last three commits.\n\n"
            + json.dumps(self.payload(["log", "-3", "--format=fuller", "--stat", "--", "."])),
        )
        effect = dispatch.consume(outcome, (folder, record), state, self.env)
        self.assertEqual(effect[0], self.env["expected"])
        self.assertEqual(record["status"], "GIT_REQUEST")
        transcript = Path(state["git_jobs"][0]["output_file"])
        self.assertIn("Change 3", transcript.read_text())
        self.assertIn(str(transcript), requests.context(self.run))
        self.assertEqual(
            json.loads((self.run / "checkpoint.json").read_text())["expected"], effect[0]
        )
        result_validation.approved_path(
            str(transcript), dict(self.roots, git_evidence=requests.output_directory(self.run))
        )
        with self.assertRaises(ValueError):
            result_validation.approved_path(str(transcript), self.roots)
        with self.assertRaisesRegex(ValueError, "not run artifacts such as changes.diff"):
            result_validation.approved_path(
                str(self.run / "changes.diff"), self.roots, result_validation.EVIDENCE_FILES
            )
        with self.assertRaisesRegex(ValueError, "cite executor snapshots only in evidence"):
            result_validation.approved_path(
                str(transcript), self.roots, result_validation.PLAN_FILES
            )

    def test_read_request_envelopes_preserve_exact_arguments(self):
        payload = self.payload(
            ["log", "-3", "--format=fuller", "--stat", "--", "ansible-playbooks"]
        )
        encoded = json.dumps(payload)
        for text in [
            encoded,
            "Now I'll issue the GIT_REQUEST.\n\n" + encoded,
            "```json\n" + encoded + "\n```",
            encoded + "\nHistory requested.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(requests.extract(text), payload)

    def test_ambiguous_or_unsafe_envelopes_never_execute(self):
        encoded = json.dumps(self.payload(["log", "-3"]))
        invalid = [
            encoded + encoded,
            '{"example": true}\n' + encoded,
            "[" + encoded + "]",
            "Now\n" + encoded[:-1],
            "Now\n" + encoded.replace('"status":', '"status": "GIT_REQUEST", "status":'),
        ]
        for argv in [
            ["add", "--", "value.txt"],
            ["commit", "-m", "Change"],
            ["reset", "--hard"],
            ["fetch", "origin"],
            ["log", "--output=bad"],
        ]:
            invalid.append("Now\n" + json.dumps(self.payload(argv)))
        with patch("countersign.git.process.invoke") as invoke:
            for text in invalid:
                self.assertIsNone(requests.extract(text), text)
                self.assertIsNone(
                    dispatch.consume(
                        dict(status="OK", final_text=text), (self.run, {}), {}, self.env
                    )
                )
            invoke.assert_not_called()
        payload = self.payload(["commit", "-m", "Change"])
        self.assertEqual(requests.extract(json.dumps(payload)), payload)

    def test_wrapped_read_still_validates_fields_root_and_mode(self):
        payload = self.payload(["status", "--short"], self.root.parent)
        parsed = requests.extract("Now\n" + json.dumps(payload))
        with self.assertRaises(ValueError):
            requests.root_path(parsed, self.roots)
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            requests.extract("Now\n" + json.dumps(payload))
        self.env["format_only"] = True
        self.assertIsNone(
            dispatch.consume(
                dict(status="OK", final_text=json.dumps(self.payload(["status"]))),
                (self.run, {}),
                {},
                self.env,
            )
        )

    def test_two_git_calls_keep_one_stage_and_explicit_session(self):
        folder = self.run / "01-plan"
        folder.mkdir()
        record = dict(
            directory=folder.name, role="planner", status="RUNNING", budget=dict(timeout=3600)
        )
        state = dict(attempts=[], stages=[record], roots={"project": str(self.root)})
        (self.run / "checkpoint.json").write_text(
            json.dumps(dict(expected=self.env["expected"], git_before=self.env["git_before"]))
        )
        launch = dict(prompt=folder / "request.md")
        requests_seen = []
        payloads = [
            self.payload(["log", "-3", "--format=fuller", "--stat"]),
            self.payload(["status", "--short"]),
            {"final": True},
        ]

        def backend(kwargs):
            requests_seen.append(
                (
                    kwargs.get("runtime"),
                    kwargs["prompt"].read_text() if kwargs["prompt"].exists() else "initial",
                )
            )
            return dict(
                status="OK",
                final_text=json.dumps(payloads[len(requests_seen) - 1]),
                sessions=["ses_one"],
                tokens=dict(total=10),
            )

        with patch("countersign.interactions.session.run_agent", side_effect=backend):
            outcome = StageSession((folder, record), state, self.env, launch).run()
        self.assertEqual(outcome["tokens"]["total"], 30)
        self.assertEqual(len(state["stages"]), 1)
        self.assertEqual(record["status"], "RUNNING")
        self.assertIsNone(requests_seen[0][0]["session_id"])
        self.assertEqual(requests_seen[1][0]["session_id"], "ses_one")
        self.assertEqual(requests_seen[2][0]["session_id"], "ses_one")
        self.assertIn("Change 3", requests_seen[1][1])
        self.assertEqual(len(list((self.run / "00-input/git").glob("*.txt"))), 2)
        events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
        self.assertEqual(
            [
                entry["part"]["tool"]
                for entry in events
                if entry["part"]["state"]["status"] == "completed"
            ],
            ["git", "git"],
        )

    def test_unknown_actions_cannot_resume(self):
        (self.run / "git-execution.json").write_text(json.dumps([dict(status="RUNNING")]))
        with self.assertRaisesRegex(ValueError, "unknown"):
            requests.context(self.run)

    def test_subproject_guards_parent_repository_metadata(self):
        child = self.root / "subproject"
        child.mkdir()
        before = git_metadata({"subproject": child})
        self.assertTrue(before)
        process.checked(self.root, ["branch", "new-branch"])
        self.assertNotEqual(before, git_metadata({"subproject": child}))

    def test_remote_push_is_non_forced_even_with_mirror_config(self):
        remote = self.base / "remote.git"
        remote.mkdir()
        process.checked(remote, ["init", "--bare"])
        process.checked(self.root, ["remote", "add", "origin", str(remote)])
        process.checked(self.root, ["config", "remote.origin.mirror", "true"])
        pushed = self.execute(["push", "origin", "HEAD:refs/heads/main"], "implementer")
        self.assertEqual(pushed["status"], "SUCCEEDED", pushed)
        process.checked(self.root, ["config", "remote.origin.mirror", "false"])
        # Advance the remote to another commit, then attempt a non-fast-forward push.
        self.file.write_text("4\n")
        process.checked(self.root, ["add", "value.txt"])
        process.checked(self.root, ["commit", "-m", "Remote advancement"])
        process.checked(self.root, ["push", "origin", "HEAD:refs/heads/main"])
        process.checked(self.root, ["checkout", "--detach", "HEAD~1"])
        rejected = self.execute(["push", "origin", "HEAD:refs/heads/main"], "implementer")
        self.assertEqual(rejected["status"], "FAILED", rejected)
        self.assertIn("rejected", rejected["stderr"])

    def test_interrupted_write_is_unknown_and_cannot_be_replayed(self):
        argv = ["revert", "--no-edit", process.checked(self.root, ["rev-parse", "HEAD"]).strip()]
        record = dict(request=self.payload(argv), status="RUNNING")
        with patch("countersign.git.execution.prepare", return_value=argv):
            with patch("countersign.git.execution.settings", return_value=[]):
                with patch(
                    "countersign.git.process.invoke",
                    side_effect=subprocess.TimeoutExpired(argv, 60),
                ):
                    execution.execute(record, [], "implementer", self.env)
        self.assertEqual(record["status"], "UNKNOWN")
        pending = json.loads((self.run / "git-execution.json").read_text())[0]
        self.assertEqual(pending["effective_argv"], argv)
        self.assertEqual(pending["status"], "RUNNING")
        with self.assertRaisesRegex(ValueError, "unknown"):
            requests.context(self.run)

    def test_external_diff_and_textconv_do_not_execute(self):
        marker = self.base / "must-not-run"
        process.checked(self.root, ["config", "diff.external", f"touch {marker}"])
        process.checked(self.root, ["config", "diff.custom.textconv", f"touch {marker}"])
        (self.root / ".gitattributes").write_text("value.txt diff=custom\n")
        self.file.write_text("4\n")
        self.assertEqual(self.execute(["diff", "--", "value.txt"])["status"], "SUCCEEDED")
        self.assertFalse(marker.exists())

    def test_history_only_plan_needs_no_project_file_read(self):
        plan = dict(
            status="PLAN_READY",
            steps=[],
            files_read=[],
            proposed_change_files=[],
            evidence=[dict(id="G1")],
        )
        validate_plan(plan, self.roots, self.base / "task.md")
        plan["evidence"] = []
        with self.assertRaises(ValueError):
            validate_plan(plan, self.roots, self.base / "task.md")

    def test_unexpected_symlink_effect_never_becomes_checkpoint(self):
        self.file.unlink()
        self.file.symlink_to(self.base / "external")
        with self.assertRaises(ValueError):
            dispatch.verify_effects(
                dict(mutation=True), snapshot(self.roots), git_metadata(self.roots), self.env
            )

    def test_not_evaluated_never_approves(self):
        payload = dict(
            status="APPROVE",
            blocking_gaps=[],
            input_complete=True,
            coverage=[dict(outcome="not_evaluated")],
        )
        with self.assertRaises(ValueError):
            coverage.verdicts(payload, "reviewer")


if __name__ == "__main__":
    unittest.main()
