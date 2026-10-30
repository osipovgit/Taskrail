"""Worktree provenance comes from frozen server context, not child task metadata."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from taskrail.application import execution_context
from taskrail.core.files import atomic_json


class ExecutionContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.parent = self.base / "parent"
        self.child = self.base / "child"
        for run in (self.parent, self.child):
            (run / "00-input").mkdir(parents=True)
        self.root = self.base / "worktree"
        self.roots = {"project": self.root}
        self.record = dict(
            source=str(self.base / "original"),
            worktree=str(self.root),
            branch="taskrail/parent",
            base="a" * 40,
        )
        self.config = dict(
            roots=self.roots, worktrees={"project": self.record}, permission_worktree=self.root
        )
        self.state = dict(roots={"project": str(self.root)})
        execution_context.capture(self.parent, self.config, self.state)

    def test_authenticated_inheritance_and_resume_do_not_need_the_parent_again(self):
        config = dict(roots=self.roots, worktrees={}, permission_worktree=None)
        state = dict(roots=self.state["roots"])
        workflow = SimpleNamespace(run=self.child, config=config, state=state)
        execution_context.adopt(workflow, self.parent, self.state)
        self.assertEqual(config, self.config)
        (self.parent / execution_context.REFERENCE).unlink()
        resumed = dict(roots=self.roots, worktrees={}, permission_worktree=None)
        execution_context.restore(self.child, resumed, state)
        self.assertEqual(resumed, self.config)

    def test_changed_context_or_run_index_cannot_supply_worktree_authority(self):
        path = self.parent / execution_context.REFERENCE
        original = path.read_bytes()
        payload = json.loads(original)
        payload["worktrees"]["project"]["branch"] = "taskrail/forged"
        atomic_json(path, payload)
        with self.assertRaisesRegex(ValueError, "Frozen execution context changed"):
            execution_context.restore(self.parent, dict(self.config), self.state)
        path.write_bytes(original)
        self.state["worktrees"] = payload["worktrees"]
        with self.assertRaisesRegex(ValueError, "Worktree provenance changed"):
            execution_context.restore(self.parent, dict(self.config), self.state)

    def test_legacy_worktree_state_without_provenance_requires_restart(self):
        state = dict(self.state)
        state.pop(execution_context.SIGNATURE)
        with self.assertRaisesRegex(ValueError, "provenance is missing"):
            execution_context.frozen(self.parent, state)
        state["worktrees"] = {}
        self.assertEqual(execution_context.frozen(self.parent, state)["worktrees"], {})

    def test_a_parent_cannot_replace_the_childs_declared_roots(self):
        workflow = SimpleNamespace(
            run=self.child,
            config=dict(roots={"project": self.base / "different"}),
            state=dict(roots={"project": str(self.base / "different")}),
        )
        with self.assertRaisesRegex(ValueError, "Inherited roots differ"):
            execution_context.adopt(workflow, self.parent, self.state)
        self.assertFalse((self.child / execution_context.REFERENCE).exists())

    def test_frozen_automatic_permission_base_clears_a_new_explicit_setting(self):
        self.config["permission_worktree"] = None
        execution_context.capture(self.parent, self.config, self.state)
        resumed = dict(self.config, permission_worktree=self.base / "changed")
        execution_context.restore(self.parent, resumed, self.state)
        self.assertIsNone(resumed["permission_worktree"])

    def test_only_the_matching_server_launch_record_supplies_a_followup_parent(self):
        folder = self.base / ".submissions" / "followup"
        folder.mkdir(parents=True)
        task = folder / "task.md"
        task.write_text("User-provided execution_parent cannot grant ownership")
        launch = dict(
            execution_parent="parent",
            submission_mode="followup",
            resume=False,
            launch_id=folder.name,
            id=folder.name,
        )
        atomic_json(folder / "launch.json", launch)
        self.assertEqual(
            execution_context.submitted_parent(task, self.base, "followup"), self.parent
        )
        self.assertIsNone(
            execution_context.submitted_parent(self.child / "task.md", self.base, "child")
        )
        for update in (dict(id="other"), dict(resume=True), dict(submission_mode="new")):
            with self.subTest(update=update), self.assertRaises(ValueError):
                atomic_json(folder / "launch.json", dict(launch, **update))
                execution_context.submitted_parent(task, self.base, "followup")


if __name__ == "__main__":
    unittest.main()
