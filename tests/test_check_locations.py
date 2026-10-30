"""Mandatory checks map descendants into owned worktrees without symlink escapes."""

import tempfile
import unittest
from pathlib import Path

from taskrail.application import check_selection


class CheckLocationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source"
        self.effective = self.base / "worktree"
        self.outside = self.base / "outside"
        for root in (self.source, self.effective, self.outside):
            root.mkdir()
        self.locations = {
            str(self.source): str(self.effective),
            str(self.effective): str(self.effective),
        }

    def test_descendant_check_maps_to_its_worktree_and_keeps_original_request(self):
        command = dict(cwd=str(self.source / "package"), argv=["python3", "--version"])
        mapped = check_selection.mapped_check(check_selection.legacy(command), self.locations)
        self.assertEqual(mapped["recipe"]["request"]["cwd"], str(self.effective / "package"))
        self.assertEqual(command["cwd"], str(self.source / "package"))

    def test_source_symlink_cannot_make_a_check_run_outside_the_declared_root(self):
        link = self.source / "escaped"
        link.symlink_to(self.outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes source root"):
            check_selection.mapped_directory(str(link), self.locations)

    def test_effective_symlink_cannot_escape_after_mapping(self):
        (self.source / "package").mkdir()
        (self.effective / "package").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes effective root"):
            check_selection.mapped_directory(str(self.source / "package"), self.locations)

    def test_unrelated_legacy_check_is_skipped_but_a_bound_check_is_rejected(self):
        check = check_selection.legacy(dict(cwd=str(self.outside), argv=["python3", "--version"]))
        self.assertIsNone(check_selection.mapped_check(check, self.locations))
        check["spec"]["criteria"] = ["R-health"]
        with self.assertRaisesRegex(ValueError, "outside the declared roots"):
            check_selection.mapped_check(check, self.locations)


if __name__ == "__main__":
    unittest.main()
