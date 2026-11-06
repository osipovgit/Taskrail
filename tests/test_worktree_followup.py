"""A fresh branch inherits pending work without mutating the previous checkout."""

import os
import tempfile
import unittest
from pathlib import Path

from taskrail.application import worktree_followup, worktree_isolation
from taskrail.git import process


class WorktreeFollowupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        process.checked(self.source, ["init", "-b", "main"])
        process.checked(self.source, ["config", "user.name", "Test"])
        process.checked(self.source, ["config", "user.email", "test@example.invalid"])
        for name in ("tracked", "deleted", "renamed", "executable"):
            (self.source / name).write_text("committed\n")
        process.checked(self.source, ["add", "."])
        process.checked(self.source, ["commit", "-m", "Initial"])

    def test_staged_unstaged_untracked_binary_modes_links_and_deletions_survive(self):
        (self.source / "tracked").write_text("staged\n")
        (self.source / "renamed").rename(self.source / "new-name")
        (self.source / "deleted").unlink()
        process.checked(self.source, ["add", "."])
        (self.source / "tracked").write_text("unstaged\n")
        (self.source / "binary").write_bytes(bytes(range(256)))
        (self.source / "executable").chmod(0o755)
        (self.source / "link").symlink_to("missing")
        before = process.checked(self.source, ["status", "--porcelain=v1", "--untracked-files=all"])
        index = process.checked(self.source, ["ls-files", "--stage", "-z"])
        config = dict(roots=dict(project=self.source), worktree_base=self.base / "worktrees")
        worktree_isolation.isolate(config, "followup")
        parent = dict(
            roots=dict(project=str(self.source)),
            worktrees=dict(project=dict(source=str(self.source))),
        )
        worktree_followup.transfer(config, parent)
        target = config["roots"]["project"]
        self.assertEqual(
            process.checked(target, ["status", "--porcelain=v1", "--untracked-files=all"]), before
        )
        self.assertEqual(process.checked(target, ["ls-files", "--stage", "-z"]), index)
        self.assertEqual(process.checked(self.source, ["ls-files", "--stage", "-z"]), index)
        self.assertEqual((target / "tracked").read_text(), "unstaged\n")
        self.assertEqual((target / "binary").read_bytes(), bytes(range(256)))
        self.assertEqual(os.readlink(target / "link"), "missing")
        self.assertTrue(os.access(target / "executable", os.X_OK))
        self.assertFalse((target / "deleted").exists())
        self.assertEqual(process.checked(self.source, ["branch", "--show-current"]).strip(), "main")
        self.assertEqual(
            process.checked(target, ["branch", "--show-current"]).strip(), "taskrail/followup"
        )

    def test_file_directory_and_symlink_replacements_preserve_complete_working_tree(self):
        (self.source / "folder/sub").mkdir(parents=True)
        (self.source / "folder/sub/old").write_text("old")
        process.checked(self.source, ["add", "."])
        process.checked(self.source, ["commit", "-m", "Directory baseline"])
        (self.source / "tracked").unlink()
        (self.source / "tracked").mkdir()
        (self.source / "tracked/new").write_text("new")
        (self.source / "folder/sub/old").unlink()
        (self.source / "folder/sub").rmdir()
        (self.source / "folder").rmdir()
        (self.source / "folder").symlink_to("tracked")
        config = dict(roots=dict(project=self.source), worktree_base=self.base / "worktrees")
        worktree_isolation.isolate(config, "replacements")
        parent = dict(
            roots=dict(project=str(self.source)),
            worktrees=dict(project=dict(source=str(self.source))),
        )
        worktree_followup.transfer(config, parent)
        target = config["roots"]["project"]
        self.assertEqual((target / "tracked/new").read_text(), "new")
        self.assertEqual(os.readlink(target / "folder"), "tracked")
        self.assertEqual(
            process.checked(target, ["status", "--porcelain", "-uall"]),
            process.checked(self.source, ["status", "--porcelain", "-uall"]),
        )

    def test_read_only_top_level_task_is_isolated_and_invalid_roots_have_no_fallback(self):
        config = dict(
            roots=dict(project=self.source), worktree_base=self.base / "worktrees", read_only=True
        )
        worktree_isolation.isolate(config, "question")
        self.assertNotEqual(config["roots"]["project"], self.source)
        config = dict(
            roots=dict(project=self.source, invalid=self.base / "missing"),
            worktree_base=self.base / "worktrees",
        )
        with self.assertRaisesRegex(ValueError, "top-level with a commit"):
            worktree_isolation.isolate(config, "invalid")
        self.assertFalse((self.base / "worktrees/invalid").exists())
        self.assertEqual(
            process.invoke(
                self.source, ["rev-parse", "--verify", "refs/heads/taskrail/invalid"]
            ).returncode,
            128,
        )
