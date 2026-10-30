"""Successful release pruning never claims unknown directories or configured roles."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.application.worktree_isolation import isolation_settings
from taskrail.core.files import atomic_json
from taskrail.deployment import releases


class ReleaseRetentionTests(unittest.TestCase):
    def test_only_unreferenced_older_successful_managed_releases_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            folders = []
            for number in range(4):
                folder = app / "releases" / str(number)
                folder.mkdir(parents=True)
                atomic_json(folder / releases.MARKER, dict(schema=1, release=folder.name))
                os.utime(folder / releases.MARKER, ns=(number + 1, number + 1))
                folders.append(folder)
            unknown = app / "releases/unknown"
            unknown.mkdir()
            (unknown / "keep").write_text("Unrecognized content")
            (app / "current").symlink_to(folders[-1], target_is_directory=True)
            settings = app / "settings.json"
            settings.write_text(json.dumps(dict(agent_source=str(folders[0] / "roles"))))
            releases.retain(app, settings)
            self.assertTrue(folders[0].exists())
            self.assertFalse(folders[1].exists())
            self.assertTrue(folders[2].exists())
            self.assertTrue(folders[3].exists())
            self.assertEqual((unknown / "keep").read_text(), "Unrecognized content")

    def test_default_worktrees_are_independent_of_resettable_history_storage(self):
        with patch("pathlib.Path.home", return_value=Path("/home/fixture")):
            config = isolation_settings({}, {}, Path("/home/fixture/.local/state/taskrail/runs"))
        self.assertEqual(
            config["worktree_base"], Path("/home/fixture/.local/share/taskrail-worktrees")
        )


if __name__ == "__main__":
    unittest.main()
