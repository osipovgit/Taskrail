"""Exercise controlled Git against disposable real repositories, never user projects."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.application import result_validation
from taskrail.application.git_state import git_metadata
from taskrail.application.plan_validation import validate_plan
from taskrail.application.source_tree import snapshot
from taskrail.core import coverage
from taskrail.git import (
    dispatch,
    execution,
    index_ownership,
    policy,
    process,
    requests,
    staging_baseline,
    staging_receipt,
)
from taskrail.interactions.session import StageSession


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

    def execute(self, argv, role="planner", previous=(), root=None):
        record = dict(request=self.payload(argv, root), status="RUNNING")
        execution.execute(record, list(previous), role, self.env)
        return record

    def second_repository_with_user_staging(self):
        other = self.base / "other"
        other.mkdir()
        process.checked(other, ["init", "-b", "main"])
        process.checked(other, ["config", "user.name", "Test"])
        process.checked(other, ["config", "user.email", "test@example.invalid"])
        user_file = other / "value.txt"
        user_file.write_text("1\n")
        process.checked(other, ["add", "value.txt"])
        process.checked(other, ["commit", "-m", "Initial"])
        user_file.write_text("Staged by the user\n")
        process.checked(other, ["add", "value.txt"])
        self.roots["other"] = other
        (self.run / "00-input/manifest.json").write_text(json.dumps(snapshot(self.roots)))
        self.env["allowed_paths"] = [self.file, user_file]
        return other

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
            ["log", "--format=%G?"],
            ["log", "--pretty", "%+GS"],
            ["show", "--format=tformat:%GG"],
            ["reflog", "--format", "signature-alias"],
            ["show", "--textconv", "HEAD:value.txt"],
            ["diff", "--no-index", "/etc/passwd", "value.txt"],
            ["branch", "-f", "main", "HEAD~1"],
            ["update-ref", "refs/heads/main", "HEAD~1"],
            ["replace", "HEAD", "HEAD~1"],
        ]
        with patch("taskrail.git.process.invoke") as invoke:
            for argv in forbidden:
                with self.subTest(argv=argv):
                    self.assertEqual(self.execute(argv, "implementer")["status"], "REJECTED")
            invoke.assert_not_called()

    def test_configured_signature_verifiers_do_not_run_during_reads(self):
        marker = self.base / "verifier-ran"
        helper = self.base / "verifier"
        helper.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        helper.chmod(0o755)
        for setting in (
            "gpg.program",
            "gpg.openpgp.program",
            "gpg.x509.program",
            "gpg.ssh.program",
        ):
            process.checked(self.root, ["config", setting, str(helper)])
        process.checked(self.root, ["config", "log.showSignature", "true"])
        process.checked(self.root, ["config", "pretty.signed", "%G?"])
        process.checked(self.root, ["config", "format.pretty", "signed"])
        tree = process.checked(self.root, ["rev-parse", "HEAD^{tree}"]).strip()
        signed = (
            f"tree {tree}\nauthor Test <test@example.invalid> 1 +0000\n"
            "committer Test <test@example.invalid> 1 +0000\n"
            "gpgsig -----BEGIN PGP SIGNATURE-----\n fake-signature\n"
            " -----END PGP SIGNATURE-----\n\nSigned fixture\n"
        )
        digest = subprocess.run(
            ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
            cwd=self.root,
            input=signed,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        for argv in (["log", "-1", digest], ["show", "--format=fuller", digest]):
            with self.subTest(argv=argv):
                self.assertFalse(policy.validate(argv, "planner"))
                self.assertIn("Signed fixture", process.checked(self.root, argv))
        # Even an internal signature probe cannot run the repository's helper.
        process.invoke(self.root, ["show", "--format=%G?", digest])
        self.assertFalse(marker.exists())

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
        with patch("taskrail.git.process.invoke") as invoke:
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

    def test_an_add_in_one_repository_does_not_own_another_index(self):
        other = self.second_repository_with_user_staging()
        self.file.write_text("4\n")
        staged = self.execute(["add", "--", "value.txt"], "implementer")
        self.assertEqual(staged["status"], "SUCCEEDED", staged)
        commit = ["commit", "-m", "Task change"]
        stolen = self.execute(commit, "implementer", [staged], other)
        self.assertEqual(stolen["status"], "REJECTED")
        self.assertIn("Only an index staged by this run", stolen["stderr"])
        added = self.execute(["add", "--", "value.txt"], "implementer", [staged], other)
        self.assertEqual(added["status"], "REJECTED")
        self.assertEqual(process.checked(other, ["log", "--format=%s"]), "Initial\n")
        self.assertEqual(process.checked(other, ["show", ":value.txt"]), "Staged by the user\n")
        committed = self.execute(commit, "implementer", [staged, stolen, added])
        self.assertEqual(committed["status"], "SUCCEEDED", committed)

    def test_two_own_commits_preserve_initial_preimages_and_unrelated_user_edits(self):
        untouched = self.root / "unrelated.txt"
        untouched.write_text("original\n")
        process.checked(self.root, ["add", "unrelated.txt"])
        process.checked(self.root, ["commit", "-m", "Independent file"])
        untouched.write_text("User changes\n")
        self.env["allowed_paths"].append(untouched)
        manifest = self.run / "00-input/manifest.json"
        manifest.write_text(json.dumps(snapshot(self.roots)))
        original = manifest.read_bytes()
        previous = []
        for number in (4, 5):
            self.file.write_text(f"{number}\n")
            staged = self.execute(["add", "--", "value.txt"], "implementer", previous)
            self.assertEqual(staged["status"], "SUCCEEDED", staged)
            previous.append(staged)
            committed = self.execute(["commit", "-m", "Task change"], "implementer", previous)
            self.assertEqual(committed["status"], "SUCCEEDED", committed)
            previous.append(committed)
        self.assertEqual(manifest.read_bytes(), original)
        denied = self.execute(["add", "--", "unrelated.txt"], "implementer", previous)
        self.assertEqual(denied["status"], "REJECTED", denied)
        self.assertIn("Preserve pre-existing user edits", denied["stderr"])
        self.assertEqual(untouched.read_text(), "User changes\n")
        self.assertEqual(process.checked(self.root, ["show", "HEAD:value.txt"]), "5\n")

    def test_controlled_delete_and_recreate_keep_originals_across_two_commits(self):
        manifest = self.run / "00-input/manifest.json"
        original = manifest.read_bytes()
        initial = process.checked(self.root, ["rev-parse", "HEAD"]).strip()
        self.file.unlink()
        removed = self.execute(["add", "--", "value.txt"], "implementer")
        self.assertEqual(removed["status"], "SUCCEEDED", removed)
        deleted = self.execute(["commit", "-m", "Task change"], "implementer", [removed])
        self.assertEqual(deleted["status"], "SUCCEEDED", deleted)
        self.assertIsNone(deleted[staging_baseline.KEY]["files"][str(self.file)])
        self.assertFalse(self.file.exists())
        self.assertEqual(process.checked(self.root, ["ls-tree", "HEAD", "--", "value.txt"]), "")
        self.assertEqual(process.checked(self.root, ["rev-parse", "HEAD^"]).strip(), initial)
        self.file.write_text("Recreated by the same approved task\n")
        previous = [removed, deleted]
        added = self.execute(["add", "--", "value.txt"], "implementer", previous)
        self.assertEqual(added["status"], "SUCCEEDED", added)
        restored = self.execute(["commit", "-m", "Task change"], "implementer", [*previous, added])
        self.assertEqual(restored["status"], "SUCCEEDED", restored)
        self.assertEqual(
            process.checked(self.root, ["show", "HEAD:value.txt"]),
            "Recreated by the same approved task\n",
        )
        self.assertEqual(
            process.checked(self.root, ["rev-parse", "HEAD^"]).strip(),
            deleted[staging_baseline.KEY]["head"],
        )
        self.assertEqual(process.checked(self.root, ["show", f"{initial}:value.txt"]), "3\n")
        self.assertEqual(manifest.read_bytes(), original)

    def test_own_commit_does_not_adopt_a_later_foreign_head_or_index(self):
        self.file.write_text("4\n")
        staged = self.execute(["add", "--", "value.txt"], "implementer")
        committed = self.execute(["commit", "-m", "Task change"], "implementer", [staged])
        self.assertEqual(committed["status"], "SUCCEEDED", committed)
        previous = [staged, committed]
        self.file.write_text("5\n")
        process.checked(self.root, ["add", "value.txt"])
        foreign_index = self.execute(["add", "--", "value.txt"], "implementer", previous)
        self.assertEqual(foreign_index["status"], "REJECTED", foreign_index)
        process.checked(self.root, ["commit", "-m", "User commit"])
        self.file.write_text("6\n")
        foreign_head = self.execute(["add", "--", "value.txt"], "implementer", previous)
        self.assertEqual(foreign_head["status"], "REJECTED", foreign_head)
        self.assertIn("Git HEAD changed", foreign_head["stderr"])

    def staged_change(self):
        self.file.write_text("4\n")
        staged = self.execute(["add", "--", "value.txt"], "implementer")
        self.assertEqual(staged["status"], "SUCCEEDED", staged)
        return staged

    def foreign_commit(self):
        unrelated = self.root / "unrelated.txt"
        unrelated.write_text("Independent user change\n")
        process.checked(self.root, ["add", "unrelated.txt"])
        process.checked(self.root, ["commit", "-m", "Foreign commit"])

    def assert_unknown_receipt(self, record):
        self.assertEqual(record["status"], "UNKNOWN", record)
        self.assertNotIn(staging_baseline.KEY, record)
        self.assertNotIn("staged", record)
        (self.run / "git-execution.json").write_text(json.dumps([record]))
        with self.assertRaisesRegex(ValueError, "unknown"):
            requests.context(self.run)
        with patch("taskrail.git.process.invoke") as invoke:
            repeated = self.execute(record["request"]["argv"], "implementer", [record])
            invoke.assert_not_called()
        self.assertEqual(repeated["status"], "REJECTED")

    def test_foreign_commit_before_receipt_cannot_be_adopted_as_controlled_history(self):
        staged = self.staged_change()
        manifest = (self.run / "00-input/manifest.json").read_bytes()
        capture = staging_baseline.snapshot

        def raced(repo, entry):
            self.foreign_commit()
            return capture(repo, entry)

        with patch.object(staging_baseline, "snapshot", side_effect=raced):
            committed = self.execute(["commit", "-m", "Own change"], "implementer", [staged])
        self.assert_unknown_receipt(committed)
        self.assertIn("history changed outside", committed["stderr"])
        self.assertEqual((self.run / "00-input/manifest.json").read_bytes(), manifest)
        self.assertEqual(
            process.checked(self.root, ["log", "-1", "--format=%s"]), "Foreign commit\n"
        )

    def test_foreign_commit_during_pinned_blob_reads_leaves_outcome_unknown(self):
        staged = self.staged_change()
        read = staging_baseline.committed
        revisions = []

        def raced(repo, path, revision):
            revisions.append(revision)
            contents = read(repo, path, revision)
            self.foreign_commit()
            return contents

        with patch.object(staging_baseline, "committed", side_effect=raced):
            committed = self.execute(["commit", "-m", "Own change"], "implementer", [staged])
        self.assert_unknown_receipt(committed)
        self.assertEqual(len(set(revisions)), 1)
        self.assertNotEqual(revisions[0], process.checked(self.root, ["rev-parse", "HEAD"]).strip())

    def test_concurrent_index_replacement_is_not_the_approved_commit(self):
        staged = self.staged_change()
        invoke = process.invoke

        def raced(root, argv, settings=()):
            if argv[0] == "commit":
                self.file.write_text("Foreign staged contents\n")
                invoke(root, ["add", "value.txt"])
            return invoke(root, argv, settings)

        with patch.object(process, "invoke", side_effect=raced):
            committed = self.execute(["commit", "-m", "Own change"], "implementer", [staged])
        self.assert_unknown_receipt(committed)
        self.assertIn("approved Git index", committed["stderr"])
        self.assertEqual(self.file.read_text(), "Foreign staged contents\n")

    def test_concurrent_extra_index_path_makes_the_outcome_unknown(self):
        staged = self.staged_change()
        invoke = process.invoke

        def raced(root, argv, settings=()):
            if argv[0] == "commit":
                (root / "unrelated.txt").write_text("Independent user change\n")
                invoke(root, ["add", "unrelated.txt"])
            return invoke(root, argv, settings)

        with patch.object(process, "invoke", side_effect=raced):
            committed = self.execute(["commit", "-m", "Own change"], "implementer", [staged])
        self.assert_unknown_receipt(committed)
        self.assertIn("history changed outside", committed["stderr"])

    def test_receipt_timeout_after_success_is_unknown_and_keeps_the_commit(self):
        staged = self.staged_change()
        before = process.checked(self.root, ["rev-parse", "HEAD"]).strip()
        with patch.object(
            staging_baseline, "snapshot", side_effect=subprocess.TimeoutExpired(["git"], 60)
        ):
            committed = self.execute(["commit", "-m", "Own change"], "implementer", [staged])
        self.assert_unknown_receipt(committed)
        self.assertNotEqual(process.checked(self.root, ["rev-parse", "HEAD"]).strip(), before)

    def test_initial_commit_records_an_unborn_start_and_all_created_paths(self):
        fresh = self.base / "fresh"
        fresh.mkdir()
        process.checked(fresh, ["init", "-b", "main"])
        process.checked(fresh, ["config", "user.name", "Test"])
        process.checked(fresh, ["config", "user.email", "test@example.invalid"])
        self.roots["fresh"] = fresh
        target = fresh / "first.txt"
        self.env["allowed_paths"].append(target)
        (self.run / "00-input/manifest.json").write_text(json.dumps(snapshot(self.roots)))
        target.write_text("First controlled commit\n")
        staged = self.execute(["add", "--", "first.txt"], "implementer", root=fresh)
        self.assertEqual(staged["status"], "SUCCEEDED", staged)
        committed = self.execute(["commit", "-m", "Initial"], "implementer", [staged], fresh)
        self.assertEqual(committed["status"], "SUCCEEDED", committed)
        self.assertIsNone(committed["head_before"])
        self.assertEqual(set(committed[staging_baseline.KEY]["files"]), {str(target)})

    def test_index_mode_changes_require_a_new_controlled_add(self):
        staged = self.staged_change()
        process.checked(self.root, ["update-index", "--chmod=+x", "value.txt"])
        rejected = self.execute(["commit", "-m", "Foreign mode"], "implementer", [staged])
        self.assertEqual(rejected["status"], "REJECTED", rejected)
        process.checked(self.root, ["update-index", "--chmod=-x", "value.txt"])
        self.file.chmod(0o755)
        added = self.execute(["add", "--", "value.txt"], "implementer", [staged])
        self.assertEqual(added["status"], "SUCCEEDED", added)
        committed = self.execute(["commit", "-m", "Own mode"], "implementer", [staged, added])
        self.assertEqual(committed["status"], "SUCCEEDED", committed)

    def test_preexisting_executable_mode_change_cannot_be_adopted_as_owned_source(self):
        self.file.chmod(0o755)
        (self.run / "00-input/manifest.json").write_text(json.dumps(snapshot(self.roots)))
        self.file.write_text("Own content after the user's chmod\n")
        rejected = self.execute(["add", "--", "value.txt"], "implementer")
        self.assertEqual(rejected["status"], "REJECTED", rejected)
        self.assertIn("pre-existing user edits", rejected["stderr"])
        self.assertEqual(process.checked(self.root, ["diff", "--cached", "--name-only"]), "")
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o755)

    def test_nonexecuting_permission_bits_do_not_count_as_git_content(self):
        self.file.chmod(0o640)
        (self.run / "00-input/manifest.json").write_text(json.dumps(snapshot(self.roots)))
        staged = self.staged_change()
        committed = self.execute(["commit", "-m", "Own content"], "implementer", [staged])
        self.assertEqual(committed["status"], "SUCCEEDED", committed)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o640)

    def applied_history_then_commit(self, command, option):
        process.checked(self.root, ["checkout", "-b", "incoming"])
        self.file.write_text("4\n")
        process.checked(self.root, ["add", "value.txt"])
        process.checked(self.root, ["commit", "-m", "Incoming change"])
        revision = process.checked(self.root, ["rev-parse", "HEAD"]).strip()
        process.checked(self.root, ["checkout", "main"])
        applied = self.execute([command, option, revision], "implementer")
        self.assertEqual(applied["status"], "SUCCEEDED", applied)
        self.file.write_text("5\n")
        staged = self.execute(["add", "--", "value.txt"], "implementer", [applied])
        self.assertEqual(staged["status"], "SUCCEEDED", staged)
        committed = self.execute(["commit", "-m", "Own edit"], "implementer", [applied, staged])
        self.assertEqual(committed["status"], "SUCCEEDED", committed)
        self.assertEqual(process.checked(self.root, ["show", "HEAD:value.txt"]), "5\n")

    def test_fast_forward_baseline_supports_a_later_own_commit(self):
        self.applied_history_then_commit("merge", "--ff-only")

    def test_cherry_pick_baseline_supports_a_later_own_commit(self):
        self.applied_history_then_commit("cherry-pick", "--no-edit")

    def test_foreign_add_before_receipt_cannot_be_adopted_as_owned_index(self):
        self.file.write_text("4\n")
        record = index_ownership.record

        def raced(root, entry):
            self.file.write_text("Foreign staged contents\n")
            process.checked(root, ["add", "value.txt"])
            record(root, entry)

        with patch.object(index_ownership, "record", side_effect=raced):
            added = self.execute(["add", "--", "value.txt"], "implementer")
        self.assert_unknown_receipt(added)
        self.assertIn("index changed outside", added["stderr"])
        self.assertEqual(self.file.read_text(), "Foreign staged contents\n")

    def test_foreign_add_during_receipt_reads_cannot_replace_an_owned_entry(self):
        self.file.write_text("4\n")
        verify = staging_receipt.verify

        def raced(repo, entry, staged):
            verify(repo, entry, staged)
            self.file.write_text("Foreign staged contents\n")
            process.checked(repo, ["add", "value.txt"])

        with patch.object(staging_receipt, "verify", side_effect=raced):
            added = self.execute(["add", "--", "value.txt"], "implementer")
        self.assert_unknown_receipt(added)
        self.assertIn("index changed outside", added["stderr"])

    def test_foreign_head_during_add_receipt_is_unknown(self):
        self.file.write_text("4\n")
        verify = staging_receipt.verify

        def raced(repo, entry, staged):
            verify(repo, entry, staged)
            process.checked(repo, ["commit", "-m", "Foreign commit of pending index"])

        with patch.object(staging_receipt, "verify", side_effect=raced):
            added = self.execute(["add", "--", "value.txt"], "implementer")
        self.assert_unknown_receipt(added)
        self.assertEqual(
            process.checked(self.root, ["log", "-1", "--format=%s"]),
            "Foreign commit of pending index\n",
        )

    def test_add_receipt_timeout_cannot_claim_index_ownership(self):
        self.file.write_text("4\n")
        with patch.object(
            staging_receipt, "verify", side_effect=subprocess.TimeoutExpired(["git"], 60)
        ):
            added = self.execute(["add", "--", "value.txt"], "implementer")
        self.assert_unknown_receipt(added)
        self.assertEqual(process.checked(self.root, ["show", ":value.txt"]), "4\n")

    def test_a_changed_staged_entry_is_not_the_runs_to_commit(self):
        self.file.write_text("4\n")
        staged = self.execute(["add", "--", "value.txt"], "implementer")
        self.assertEqual(staged["status"], "SUCCEEDED", staged)
        self.file.write_text("Changed and staged by the user\n")
        process.checked(self.root, ["add", "value.txt"])
        commit = self.execute(["commit", "-m", "Task change"], "implementer", [staged])
        self.assertEqual(commit["status"], "REJECTED")
        self.assertEqual(process.checked(self.root, ["log", "-1", "--format=%s"]), "Change 3\n")

    def test_a_new_add_after_edits_runs_but_a_replay_or_uncertain_write_does_not(self):
        add = ["add", "--", "value.txt"]
        self.file.write_text("4\n")
        first = self.execute(add, "implementer")
        self.assertEqual(first["status"], "SUCCEEDED", first)
        replay = self.execute(add, "implementer", [first])
        self.assertEqual(replay["status"], "REJECTED")
        self.assertIn("Do not replay", replay["stderr"])
        self.file.write_text("5\n")
        second = self.execute(add, "implementer", [first, replay])
        self.assertEqual(second["status"], "SUCCEEDED", second)
        self.assertEqual(process.checked(self.root, ["show", ":value.txt"]), "5\n")
        commit = self.execute(["commit", "-m", "Task change"], "implementer", [first, second])
        self.assertEqual(commit["status"], "SUCCEEDED", commit)
        self.assertEqual(process.checked(self.root, ["show", "HEAD:value.txt"]), "5\n")
        uncertain = dict(first, status="UNKNOWN")
        self.file.write_text("6\n")
        with patch("taskrail.git.process.invoke") as invoke:
            again = self.execute(add, "implementer", [uncertain])
            invoke.assert_not_called()
        self.assertEqual(again["status"], "REJECTED")

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
        with patch("taskrail.git.process.invoke") as invoke:
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
            directory=folder.name,
            stage="planner",
            role="planner",
            status="RUNNING",
            budget=dict(timeout=3600),
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

        with patch("taskrail.interactions.session.run_agent", side_effect=backend):
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
        with (
            patch("taskrail.git.execution.prepare", return_value=argv),
            patch("taskrail.git.execution.settings", return_value=[]),
            patch(
                "taskrail.git.process.invoke",
                side_effect=subprocess.TimeoutExpired(argv, 60),
            ),
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
