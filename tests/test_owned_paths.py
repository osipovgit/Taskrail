"""Authority paths reject traversal and aliases, including aliases within storage."""

import tempfile
import unittest
from pathlib import Path

from taskrail.core import owned_paths


class OwnedPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def test_missing_fixed_descendants_are_valid_without_creating_them(self):
        expected = self.base / "pending.v2/00-input/task.md"
        self.assertEqual(owned_paths.child(self.base, "pending.v2/00-input/task.md"), expected)
        self.assertFalse(expected.exists())

    def test_parent_absolute_and_same_directory_references_are_rejected(self):
        for relative in ("../outside", "/etc/passwd", ".", "", "child/../sibling"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                owned_paths.child(self.base, relative)
        with self.assertRaises(ValueError):
            owned_paths.child(Path("/"), ".")

    def test_aliases_inside_and_outside_storage_are_not_authority(self):
        target = self.base / "real"
        target.mkdir()
        for name, destination in (("inside", target), ("outside", self.base.parent)):
            (self.base / name).symlink_to(destination, target_is_directory=True)
            with self.subTest(name=name), self.assertRaises(ValueError):
                owned_paths.child(self.base, f"{name}/run.json")
        with self.assertRaises(ValueError):
            owned_paths.child(self.base / "inside", "run.json")
