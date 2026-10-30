"""Real linked worktrees retain ownership, checks and provider permissions across a split."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_reviewed_workflow import ReviewedFixture

from taskrail.application import execution_context
from taskrail.application.live import execute_task
from taskrail.core.files import atomic_json
from taskrail.core.requirements import requirement
from taskrail.git import process
from taskrail.web import epic_launch, epic_tasks, integration_review, submissions


class IsolatedSplitFixture(ReviewedFixture):
    def repository(self):
        (self.root / ".git/HEAD").unlink()
        (self.root / ".git").rmdir()
        process.checked(self.root, ["init", "-b", "main"])
        process.checked(self.root, ["config", "user.name", "Fixture"])
        process.checked(self.root, ["config", "user.email", "fixture@example.invalid"])
        process.checked(self.root, ["add", "."])
        process.checked(self.root, ["commit", "-m", "Initial"])

    def split(self):
        self.repository()
        self.settings_extra = dict(
            worktree_base=str(self.base / "worktrees"),
            verify_commands=[
                dict(
                    cwd=str(self.root),
                    argv=[
                        sys.executable,
                        "-c",
                        "from pathlib import Path; assert 'return 2' in Path('hello.py').read_text()",
                    ],
                )
            ],
        )
        self.settings_extra.update(getattr(self, "split_settings", {}))
        if self.provider == "fake_opencode_two.py":
            self.settings_extra["opencode_version"] = "2.x"
        fields = dict(
            goal="Return 2 and add the new module",
            criteria="Both outputs work",
            auto_approve=True,
            worktree=True,
            roots=[dict(alias="project", path=str(self.root))],
        )
        if getattr(self, "bound_checks", False):
            command = self.settings_extra["verify_commands"][0]
            self.settings_extra["check_recipes"] = dict(
                health=dict(kind="local", phase="check", request=command, adapter="exit-code")
            )
            fields["verification"] = "Health check passes"
            fields["check_specs"] = [
                dict(
                    id="C-health",
                    recipe_id="health",
                    phase="check",
                    parameters={},
                    criteria=[requirement("Health check passes", "runtime")["id"]],
                )
            ]
        parent, status, state = self.execute("parent", fields, "two-tasks")
        self.assertEqual(status, "TASKS_READY", state.get("summary"))
        return parent, state

    def start_child(self, parent, state, linked, number, mode, name=None):
        entries = epic_tasks.tasks(parent, state)
        current = entries[number - 1]
        name = name or f"child-{number}"
        linked[current["id"]] = name
        path = parent / "epic.json"
        epic = json.loads(path.read_text()) if path.exists() else {}
        epic["tasks"] = linked
        epic.setdefault("attempts", {}).setdefault(current["id"], []).append(name)
        atomic_json(path, epic)
        payload = epic_launch.payload(parent, state, entries, current)
        return self.execute(name, payload, mode)

    def assert_checks(self, state, worktree):
        checks = [check for check in state["checks"] if "cwd" in check]
        self.assertEqual(len(checks), 1, state)
        self.assertEqual((checks[0]["status"], checks[0]["cwd"]), ("PASS", str(worktree)))

    def complete_split(self):
        parent, state = self.split()
        record = state["worktrees"]["project"]
        worktree = Path(record["worktree"])
        self.assertTrue((worktree / ".git").is_file())
        linked = {}
        for number, mode in enumerate(("ok", "new"), 1):
            child, status, finished = self.start_child(parent, state, linked, number, mode)
            self.assertEqual(status, "READY_FOR_REVIEW", finished.get("summary"))
            self.assertEqual(finished["worktrees"], state["worktrees"])
            self.assertEqual(len(finished["commits"]), 1)
            self.assert_checks(finished, worktree)
            frozen = execution_context.frozen(child, finished)
            self.assertEqual(frozen["permission_worktree"], str(worktree))
        atomic_json(parent / "epic.json", dict(tasks=linked, phases=dict(integration="combined")))
        if getattr(self, "bound_checks", False):
            self.settings_extra["check_recipes"] = {}
        review, status, accepted = self.execute(
            "combined", integration_review.payload(parent, state)
        )
        self.assertEqual(status, "NO_CHANGES_REQUIRED", accepted.get("summary"))
        self.assert_checks(accepted, worktree)
        self.assertEqual([entry["stage"] for entry in accepted["stages"]], ["check", "reviewer"])
        self.assertEqual(accepted["worktrees"], state["worktrees"])
        self.assertIn("-    return 1", (review / "changes.diff").read_text())
        self.assertIn("new.py", (review / "changes.diff").read_text())
        self.assertIn("return 1", (self.root / "hello.py").read_text())
        self.assertFalse((self.root / "new.py").exists())
        self.assertEqual(process.checked(worktree, ["status", "--porcelain"]), "")
        commits = process.checked(worktree, ["rev-list", "--count", record["base"] + "..HEAD"])
        self.assertEqual(commits.strip(), "2")


class IsolatedSplitTests(IsolatedSplitFixture, unittest.TestCase):
    def test_one_x_children_commit_and_integration_repeats_source_mapped_checks(self):
        self.provider = "fake_live.py"
        self.bound_checks = True
        self.complete_split()

    def test_two_x_children_and_integration_keep_linked_worktree_permissions(self):
        self.provider = "fake_opencode_two.py"
        self.complete_split()

    def test_resume_uses_own_worktree_seal_after_parent_removal(self):
        self.provider = "fake_live.py"
        parent, state = self.split()
        child, status, stopped = self.start_child(parent, state, {}, 1, "writer-timeout")
        self.assertEqual(status, "TIMEOUT", stopped.get("summary"))
        (parent / "run.json").unlink()
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        settings["timeout_seconds"] = 10
        atomic_json(self.settings, settings)
        _, status = execute_task(
            child / "00-input/task.md", self.settings, run_dir=child, resume=True
        )
        finished = json.loads((child / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", finished.get("summary"))
        self.assertEqual(finished["worktrees"], state["worktrees"])
        self.assertEqual(len(finished["commits"]), 1)
        self.assert_checks(finished, Path(state["worktrees"]["project"]["worktree"]))

    def test_explicit_child_restart_reuses_ownership_and_commits_prior_attempt_edits(self):
        self.provider = "fake_live.py"
        parent, state = self.split()
        linked = {}
        _, status, failed = self.start_child(
            parent, state, linked, 1, "writer-extra-prose-always", "failed"
        )
        self.assertEqual(status, "INVALID_RESULT", failed.get("summary"))
        _, status, finished = self.start_child(parent, state, linked, 1, "ok", "restarted")
        self.assertEqual(status, "READY_FOR_REVIEW", finished.get("summary"))
        self.assertEqual(finished["worktrees"], state["worktrees"])
        self.assertEqual(len(finished["commits"]), 1)
        worktree = Path(state["worktrees"]["project"]["worktree"])
        self.assert_checks(finished, worktree)
        self.assertEqual(process.checked(worktree, ["status", "--porcelain"]), "")
        self.assertIn("extra.txt", process.checked(worktree, ["show", "--stat", "HEAD"]))
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_server_followup_reuses_sealed_worktree_with_a_fresh_reviewed_plan(self):
        self.provider = "fake_live.py"
        parent, state = self.split()
        payload = dict(
            parent_run=parent.name,
            submission_mode="followup",
            goal="Return two",
            criteria="Function returns two",
            auto_approve=True,
            roots=[dict(alias="project", path=str(self.root))],
        )
        launcher = submissions.TaskLauncher(self.runs, settings=self.settings, recover=False)
        with patch.object(launcher, "launch") as launch:
            launcher.submit(payload)
        folder, manifest = submissions.create_submission(self.runs, launch.call_args.args[0])
        self.assertEqual(manifest["execution_parent"], parent.name)
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        settings["permission_worktree"] = str(self.base / "removed-current-base")
        atomic_json(self.settings, settings)
        run, status = execute_task(
            folder / "task.md", self.settings, run_dir=self.runs / manifest["id"]
        )
        finished = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", finished.get("summary"))
        self.assertEqual(finished["worktrees"], state["worktrees"])
        self.assertEqual(len(finished["commits"]), 1)
        self.assertEqual(finished["attempts"][0]["stage"], "planner")
        self.assertNotIn("contract_start", finished)
        self.assert_checks(finished, Path(state["roots"]["project"]))
        self.assertIn("return 1", (self.root / "hello.py").read_text())


if __name__ == "__main__":
    unittest.main()
