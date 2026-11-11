"""Atomic replacement of run artifacts and private executor tickets."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.core.files import atomic_json, atomic_output, atomic_write


class AtomicFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.path = self.directory / "run.json"

    def test_a_partial_write_cannot_damage_the_previous_state_or_leave_a_temp_file(self):
        atomic_json(self.path, {"round": 1})
        previous = self.path.read_bytes()
        with self.assertRaises(TypeError):
            atomic_json(self.path, {"partial": "written first", "invalid": object()})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_overlapping_writers_each_publish_their_own_complete_version(self):
        with atomic_output(self.path, "wb") as outer:
            outer.write(b'{"round":')
            atomic_write(self.path, b'{"round":2}')
            self.assertEqual(json.loads(self.path.read_bytes()), {"round": 2})
            outer.write(b"1}")
        self.assertEqual(json.loads(self.path.read_bytes()), {"round": 1})
        self.assertEqual(list(self.directory.iterdir()), [self.path])
