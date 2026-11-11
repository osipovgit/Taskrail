"""Source checkout names can identify future targets, never substitute for observed evidence."""

import copy
import tempfile
import unittest
from pathlib import Path

from taskrail.application import plan_validation, workspace_paths
from taskrail.application.planned_paths import safe_file


class WorkspacePathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source checkout"
        self.target = self.base / "worktrees/current/admin"
        self.source.mkdir()
        self.target.mkdir(parents=True)
        self.config = dict(
            roots=dict(admin=self.target),
            worktrees=dict(admin=dict(source=str(self.source), worktree=str(self.target))),
        )

    def test_only_future_targets_and_read_hints_are_translated(self):
        name = str(self.source / "ansible-playbooks/site.yml")
        payload = dict(
            proposed_change_files=[name],
            files_read=[name],
            evidence=[dict(path=name, line_start=1, line_end=2)],
            steps=[dict(files=[name], read=[f"{name}:1-2", name], notes=name)],
            summary=name,
        )
        original = copy.deepcopy(payload)
        workspace_paths.plan_targets(payload, self.config)
        target = str(self.target / "ansible-playbooks/site.yml")
        self.assertEqual(payload["proposed_change_files"], [target])
        self.assertEqual(payload["steps"][0]["files"], [target])
        self.assertEqual(payload["steps"][0]["read"], [f"{target}:1-2", target])
        for field in ("files_read", "evidence", "summary"):
            self.assertEqual(payload[field], original[field])
        self.assertEqual(payload["steps"][0]["notes"], name)

    def test_sibling_old_run_traversal_and_symlink_paths_are_not_guessed(self):
        link = self.source / "linked"
        link.symlink_to(self.target, target_is_directory=True)
        paths = (
            self.base / "source checkout-other/site.yml",
            self.base / "worktrees/old/admin/site.yml",
            self.source / "child/../site.yml",
            link / "site.yml",
            self.target / "site.yml",
        )
        mapping = workspace_paths.mappings(self.config)
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(workspace_paths.resolve(str(path), mapping), path)

    def test_missing_or_mismatched_worktree_provenance_cannot_translate(self):
        for config in ({}, dict(self.config, roots=dict(admin=self.base / "other"))):
            with self.subTest(config=config):
                self.assertEqual(workspace_paths.mappings(config), [])
                self.assertEqual(workspace_paths.instructions(config), "")

    def test_nested_sources_choose_the_most_specific_authenticated_root(self):
        nested = self.source / "nested"
        nested.mkdir()
        other = self.base / "worktrees/current/nested"
        other.mkdir()
        self.config["roots"]["nested"] = other
        self.config["worktrees"]["nested"] = dict(source=str(nested), worktree=str(other))
        mapping = workspace_paths.mappings(self.config)
        self.assertEqual(workspace_paths.resolve(nested / "file.py", mapping), other / "file.py")
        self.assertEqual(
            workspace_paths.resolve(self.source / "file.py", mapping), self.target / "file.py"
        )

    def test_translated_targets_still_reject_protected_symlinked_and_duplicate_files(self):
        link = self.target / "linked"
        link.symlink_to(self.source, target_is_directory=True)
        mapping = workspace_paths.mappings(self.config)
        for relative in (".git/config", "linked/file.py"):
            with self.subTest(relative=relative):
                mapped = workspace_paths.resolve(self.source / relative, mapping)
                alias = plan_validation.alias_path(str(mapped), self.config["roots"])
                with self.assertRaises(ValueError):
                    safe_file(alias, self.config["roots"])
        mapped = workspace_paths.resolve(self.source / "file.py", mapping)
        with self.assertRaisesRegex(ValueError, "unique"):
            plan_validation.unique_names([str(mapped), str(self.target / "file.py")])
