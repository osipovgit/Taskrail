"""On a Taskrail branch a task may go beyond its plan and ends in one reviewed commit."""

import json
import tempfile
import unittest
from pathlib import Path

from live_fixture import LiveFixture

from taskrail.application import child_brief, mode_rules, task_branch
from taskrail.application.delivery_confirmation import review_guard
from taskrail.core import prompt_texts
from taskrail.infrastructure import profile_rules


class TaskBranchRunTests(LiveFixture, unittest.TestCase):
    def isolated(self, mode):
        self.git = self.real_repository()
        header = {"roots": {"project": str(self.root)}, "isolation": "worktree"}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        run, status, state = self.run_mode(mode, worktree_base=str(self.base / "worktrees"))
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertTrue(state[task_branch.KEY])
        return run, state, Path(state["worktrees"]["project"]["worktree"])

    def test_an_approved_task_is_one_commit_on_its_branch(self):
        run, state, worktree = self.isolated("ok")
        branch = f"taskrail/{run.name}"
        base = state["worktrees"]["project"]["base"]
        count = self.git.checked(self.root, ["rev-list", "--count", f"{base}..{branch}"])
        self.assertEqual(count.strip(), "1")
        message = self.git.checked(self.root, ["log", "-1", "--format=%B", branch])
        self.assertIn(f"Taskrail-Run: {run.name}", message)
        head = self.git.checked(self.root, ["rev-parse", branch]).strip()
        self.assertEqual(state["commits"], [dict(root="project", commit=head)])
        self.assertEqual(self.git.checked(worktree, ["status", "--porcelain"]), "")
        self.assertTrue(review_guard(run).git_unchanged())
        self.assertIn(f"- project: `{head}`", (run / "report.md").read_text())
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_the_implementer_may_change_files_beyond_the_plan(self):
        run, state, worktree = self.isolated("scope")
        self.assertEqual(state[task_branch.BEYOND], ["project/unrelated.txt"])
        diff = (run / "changes.diff").read_text()
        self.assertIn("-user dirty work", diff)
        self.assertIn("+corrupted", diff)
        committed = self.git.checked(worktree, ["show", "--name-only", "--format=", "HEAD"])
        self.assertEqual(sorted(committed.split()), ["hello.py", "unrelated.txt"])
        self.assertIn("## Changed beyond the plan", (run / "report.md").read_text())
        self.assertEqual((self.root / "unrelated.txt").read_text(), "user dirty work\n")

    def test_in_place_the_plan_still_limits_the_files(self):
        self.real_repository()
        _, status, state = self.run_mode("scope")
        self.assertNotEqual(status, "READY_FOR_REVIEW")
        self.assertFalse(state[task_branch.KEY])
        self.assertNotIn("commits", state)


class TaskBranchRuleTests(unittest.TestCase):
    def test_writable_roots_never_make_git_metadata_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rules = profile_rules.permissions([root], [], [root], base=root)["edit"]
        self.assertEqual(rules["*"], profile_rules.ALLOW)
        self.assertEqual(rules[f"{root}/*"], profile_rules.ALLOW)
        for metadata in profile_rules.GIT_METADATA:
            self.assertEqual(rules[metadata], profile_rules.DENY)
        self.assertEqual(rules["*/.env"], profile_rules.DENY)
        self.assertEqual(list(rules)[-1], profile_rules.GIT_METADATA[-1])

    def test_branch_rules_reach_the_writer_and_its_reviewer_only(self):
        config = {task_branch.KEY: True}
        self.assertIn("own Git branch", mode_rules.render(config, "implementer"))
        self.assertIn("beyond the plan", mode_rules.render(config, "reviewer"))
        self.assertNotIn("own Git branch", mode_rules.render({}, "implementer"))
        integration = dict(config, phase="integration")
        self.assertNotIn("beyond the plan", mode_rules.render(integration, "reviewer"))
        child = dict(config, phase="task", assigned_contract=dict(task_id="T2"))
        rule = mode_rules.render(child, "implementer")
        self.assertIn("may already contain parts of yours", rule)
        self.assertIn("Do not split hunks mechanically", rule)

    def test_a_task_brief_names_the_later_tasks_as_not_to_do(self):
        steps = [
            dict(id="T1", title="Parser", files=["project/parser.py"], depends_on=[]),
            dict(id="T2", title="Command", files=["project/cli.py"], depends_on=["T1"]),
            dict(id="T3", title="Docs", files=["project/README.md"], depends_on=["T2"]),
        ]
        parent = dict(run=Path("/runs/parent"), plan=dict(steps=steps), epic={})
        brief = child_brief.context(parent, steps[1])
        earlier, later = brief.split(prompt_texts.text("child.later"))
        self.assertIn("- T1: Parser", earlier)
        self.assertEqual(later.strip(), "- T3: Docs. Files: project/README.md")


if __name__ == "__main__":
    unittest.main()
