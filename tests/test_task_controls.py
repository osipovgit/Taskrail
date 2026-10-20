"""Task lifecycle controls, history isolation and answer-only execution."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from countersign.application.live import execute_task
from countersign.web import epic_launch, requests
from countersign.web.history import HISTORY, conversation, previous_messages, task_draft
from countersign.web.lifecycle import trash_run
from countersign.web.run_list import list_runs
from countersign.web.run_view import run_view
from countersign.web.submissions import TaskLauncher
from countersign.web.task_form import build_task

BASE = Path(__file__).resolve().parents[1]


class TaskControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.repo / "hello.py").write_text("def hello():\n    return 1\n")
        self.runs = self.base / "runs"
        self.payload = dict(
            title="Original",
            goal="Return 2",
            criteria="Preserve other files",
            roots=[dict(alias="project", path=str(self.repo))],
        )
        self.run = self.runs / "original"
        (self.run / "00-input").mkdir(parents=True)
        text, _ = build_task(self.payload, self.runs)
        (self.run / "00-input/task.md").write_text(text)
        (self.run / "run.json").write_text(
            json.dumps(
                dict(
                    status="READY_FOR_REVIEW",
                    roots={"project": str(self.repo)},
                    summary="Previous conclusion",
                    results={"plan": "plan.json"},
                    stages=[],
                )
            )
        )
        (self.run / "plan.json").write_text(
            json.dumps(dict(status="PLAN_READY", summary="Evidence"))
        )
        (self.run / "changes.diff").write_text("-return 1\n+return 2\n")
        self.settings = self.base / "settings.json"
        self.configure("ok")
        self.launcher = TaskLauncher(self.runs, self.settings)

    def configure(self, mode):
        self.settings.write_text(
            json.dumps(
                dict(
                    command=[
                        sys.executable,
                        str(BASE / "tests/fake_live.py"),
                        "--profiles",
                        str(self.base / "profiles"),
                        "--mode",
                        mode,
                    ],
                    agent_source=str(BASE / "countersign/agents"),
                    agent_directory=str(self.base / "profiles"),
                    timeout_seconds=30,
                    max_read_retries=0,
                )
            )
        )

    def wait_for(self, predicate):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail("Worker did not reach the expected state")

    def test_restart_returns_editable_draft_without_launching(self):
        with patch.object(self.launcher, "launch") as launch:
            result = self.launcher.action(dict(id="original", action="restart"))
            launch.assert_not_called()
        self.assertEqual(result["draft"]["goal"], "Return 2")
        self.assertEqual(result["draft"]["roots"], self.payload["roots"])
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(
                dict(
                    result["draft"],
                    goal="Return 3",
                    parent_run="original",
                    submission_mode="restart",
                )
            )
            text = launch.call_args.args[0]["text"]
            self.assertIn("## Goal\nReturn 3", text)
            self.assertNotIn(HISTORY, text)
        self.assertEqual(task_draft(self.run)["goal"], "Return 2")

    def test_followup_snapshots_evidence_and_survives_parent_deletion(self):
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(
                dict(
                    self.payload,
                    goal="Explain the result",
                    parent_run="original",
                    submission_mode="answer",
                )
            )
            text = launch.call_args.args[0]["text"]
        meta = json.loads(text.split("```countersign-task\n")[1].split("```")[0])
        self.assertTrue(meta["read_only"])
        self.assertIn("Previous conclusion", text)
        self.assertIn("Evidence", text)
        self.assertIn("-return 1", text)
        child = self.runs / "child"
        (child / "00-input").mkdir(parents=True)
        (child / "00-input/task.md").write_text(text)
        (child / "run.json").write_text((self.run / "run.json").read_text())
        trash_run(self.runs, self.run)
        self.assertEqual(previous_messages(child)[0]["goal"], "Return 2")
        self.assertEqual(task_draft(child)["goal"], "Explain the result")
        self.assertNotIn("Answer only", task_draft(child)["constraints"])

    def test_worktree_flag_is_a_boolean_task_header_option(self):
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(dict(self.payload, worktree=True, read_only=True))
            text = launch.call_args.args[0]["text"]
        meta = json.loads(text.split("```countersign-task\n")[1].split("```")[0])
        self.assertEqual(meta["isolation"], "worktree")
        self.assertTrue(meta["read_only"])
        with self.assertRaisesRegex(ValueError, "boolean"):
            self.launcher.submit(dict(self.payload, worktree="yes"))
        child = self.runs / "isolated"
        (child / "00-input").mkdir(parents=True)
        (child / "00-input/task.md").write_text(text)
        index = json.loads((self.run / "run.json").read_text())
        source = index["roots"]["project"]
        index["roots"]["project"] = "/worktrees/isolated/project"
        index["worktrees"] = {"project": {"source": source}}
        (child / "run.json").write_text(json.dumps(index))
        draft = task_draft(child)
        self.assertTrue(draft["worktree"])
        self.assertEqual(draft["roots"], [{"alias": "project", "path": source}])
        followup = requests.Submission(
            dict(draft, parent_run="isolated", submission_mode="followup"), self.runs
        )
        self.assertFalse(followup.worktree)
        self.assertEqual(followup.fields["roots"][0]["path"], "/worktrees/isolated/project")
        restart = requests.Submission(
            dict(draft, parent_run="isolated", submission_mode="restart"), self.runs
        )
        self.assertTrue(restart.worktree)
        self.assertEqual(restart.fields["roots"][0]["path"], source)

    def test_allow_all_actions_is_a_header_option_kept_in_the_draft(self):
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(dict(self.payload, auto_approve=True))
            text = launch.call_args.args[0]["text"]
        meta = json.loads(text.split("```countersign-task\n")[1].split("```")[0])
        self.assertIs(meta["auto_approve"], True)
        (self.run / "00-input/task.md").write_text(text)
        self.assertTrue(task_draft(self.run)["auto_approve"])
        with self.assertRaisesRegex(ValueError, "boolean"):
            self.launcher.submit(dict(self.payload, auto_approve="yes"))

    def test_design_discussion_is_read_only_and_asks_for_a_document(self):
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(dict(self.payload, design=True))
            text = launch.call_args.args[0]["text"]
        meta = json.loads(text.split("```countersign-task\n")[1].split("```")[0])
        self.assertTrue(meta["design"])
        self.assertTrue(meta["read_only"])
        self.assertIn("Design discussion: no edits", text)
        self.assertNotIn("Answer only", text)
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(
                dict(
                    self.payload,
                    goal="Compare caching options",
                    parent_run="original",
                    submission_mode="design",
                )
            )
            followup = launch.call_args.args[0]["text"]
        self.assertIn('"design": true', followup)
        self.assertIn("Conversation history", followup)

    def make_epic(self):
        epic = self.runs / "epic"
        (epic / "00-input").mkdir(parents=True)
        text, _ = build_task(dict(self.payload, goal="Return 2 and document it"), self.runs)
        decorated = text.replace('"roots":', '"decompose": true, "auto_approve": true, "roots":', 1)
        (epic / "00-input/task.md").write_text(decorated)
        steps = [
            dict(
                id="S-1",
                action="Change hello: return 2",
                files=[],
                criteria=[],
                depends_on=[],
                checks=["hello returns 2"],
            ),
            dict(
                id="S-2",
                action="Document hello: describe the value",
                files=[],
                criteria=[],
                depends_on=["S-1"],
                checks=["README mentions 2"],
            ),
        ]
        (epic / "plan.json").write_text(json.dumps(dict(steps=steps)))
        index = dict(
            status="TASKS_READY",
            roots={"project": str(self.repo)},
            results={"plan": "plan.json"},
            stages=[],
        )
        (epic / "run.json").write_text(json.dumps(index))
        return epic

    def finish(self, name, status):
        child = self.runs / name
        (child / "00-input").mkdir(parents=True, exist_ok=True)
        (child / "00-input/task.md").write_text("# child\n")
        state = dict(status=status, summary=f"{name} summary", changed_files=["/repo/hello.py"])
        (child / "run.json").write_text(json.dumps(state))

    def test_task_split_starts_tasks_in_order_with_a_brief(self):
        epic = self.make_epic()
        epic_entry = next(run for run in list_runs(self.runs) if run["id"] == "epic")
        self.assertEqual((epic_entry["group"], epic_entry["progress"]), ("attention", "0/2"))
        self.assertEqual(epic_entry["mode"], "decompose")
        view = run_view(self.runs, "epic")["epic"]
        self.assertEqual(view["next"], "S-1")
        with patch.object(self.launcher, "launch", return_value={"id": "child-1"}) as launch:
            self.launcher.action(dict(id="epic", action="epic_next"))
            text = launch.call_args.args[0]["text"]
        self.assertIn("Change hello: return 2", text)
        self.assertIn("S-1: Change hello (current task)", text)
        self.assertIn("S-2: Document hello (later; not part of this run)", text)
        self.assertIn('"auto_approve": true', text)
        self.assertNotIn('"decompose"', text)
        self.assertNotIn("Conversation history", text)
        self.assertEqual(json.loads((epic / "epic.json").read_text())["tasks"], {"S-1": "child-1"})
        with self.assertRaisesRegex(ValueError, "No task is ready"):
            self.launcher.action(dict(id="epic", action="epic_next"))
        self.finish("child-1", "TOOL_ERROR")
        self.assertEqual(run_view(self.runs, "epic")["epic"]["next"], None)
        self.launcher.action(dict(id="epic", action="epic_auto_on"))
        with patch.object(self.launcher, "launch") as launch:
            epic_launch.advance(self.launcher)
        launch.assert_not_called()
        self.finish("child-1", "READY_FOR_REVIEW")
        with patch.object(self.launcher, "launch", return_value={"id": "child-2"}) as launch:
            epic_launch.advance(self.launcher)
            text = launch.call_args.args[0]["text"]
        self.assertIn("S-1: Change hello (READY_FOR_REVIEW): child-1 summary", text)
        self.finish("child-2", "READY_FOR_REVIEW")
        epic_entry = next(run for run in list_runs(self.runs) if run["id"] == "epic")
        self.assertEqual((epic_entry["group"], epic_entry["progress"]), ("review", "2/2"))

    def test_allow_all_actions_can_be_revoked_from_the_ui(self):
        index = self.run / "run.json"
        index.write_text(json.dumps(dict(json.loads(index.read_text()), auto_approve=True)))
        view = run_view(self.runs, "original")
        self.assertTrue(view["auto_approve"])
        self.assertTrue(view["actions"]["revoke_auto_approve"])
        self.launcher.action(dict(id="original", action="revoke_auto_approve"))
        view = run_view(self.runs, "original")
        self.assertFalse(view["auto_approve"])
        self.assertFalse(view["actions"]["revoke_auto_approve"])

    def test_runs_are_grouped_by_what_they_need_and_can_be_marked_done(self):
        def group():
            return list_runs(self.runs)[0]["group"]

        index = self.run / "run.json"
        state = json.loads(index.read_text())
        self.assertEqual(group(), "review")
        self.assertEqual(list_runs(self.runs)[0]["mode"], "change")
        self.launcher.action(dict(id="original", action="done"))
        self.assertEqual(group(), "done")
        self.assertTrue(run_view(self.runs, "original")["actions"]["reopen"])
        self.launcher.action(dict(id="original", action="reopen"))
        self.assertEqual(group(), "review")
        self.launcher.action(dict(id="original", action="done"))
        index.write_text(json.dumps(dict(state, status="TOOL_ERROR", finished_at="later")))
        self.assertEqual(group(), "attention")
        index.write_text(json.dumps(dict(state, status="NO_CHANGES_REQUIRED")))
        self.assertEqual(group(), "done")
        running = dict(state, status="RUNNING", execution_jobs=[dict(status="PENDING_APPROVAL")])
        index.write_text(json.dumps(running))
        self.assertEqual(list_runs(self.runs)[0]["status"], "WAITING_APPROVAL")
        self.assertEqual(group(), "attention")
        index.write_text(json.dumps(dict(running, execution_jobs=[])))
        self.assertEqual(group(), "running")
        with self.assertRaisesRegex(ValueError, "stopped"):
            self.launcher.action(dict(id="original", action="done"))

    def test_delete_moves_all_launcher_history_but_preserves_sources(self):
        for name in ("original-launch", "resume-launch"):
            folder = self.runs / ".submissions" / name
            folder.mkdir(parents=True)
            (folder / "launch.json").write_text(json.dumps(dict(id="original", status="RUNNING")))
        before = (self.repo / "hello.py").read_bytes()
        self.launcher.action(dict(id="original", action="delete"))
        self.assertFalse(self.run.exists())
        self.assertEqual(list_runs(self.runs), [])
        self.assertEqual((self.repo / "hello.py").read_bytes(), before)
        trash = self.runs / ".trash/original"
        self.assertTrue((trash / "run/changes.diff").exists())
        self.assertTrue((trash / "resume-launch/launch.json").exists())

    def test_delete_failed_launch_without_run_index(self):
        folder = self.runs / ".submissions/failed"
        folder.mkdir(parents=True)
        (folder / "launch.json").write_text(json.dumps(dict(id="failed", status="LAUNCH_ERROR")))
        self.launcher.action(dict(id="failed", action="delete"))
        self.assertFalse(folder.exists())
        self.assertTrue((self.runs / ".trash/failed/failed/launch.json").exists())

    def test_delete_rejects_running_runs_traversal_and_symlinks(self):
        state = json.loads((self.run / "run.json").read_text())
        state["status"] = "RUNNING"
        (self.run / "run.json").write_text(json.dumps(state))
        (self.runs / "alias").symlink_to(self.repo)
        for name in ("original", "..", "alias"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.launcher.action(dict(id=name, action="delete"))
        self.assertTrue(self.run.exists())

    def test_history_refuses_external_artifacts_and_oversized_context(self):
        (self.run / "plan.json").unlink()
        (self.run / "plan.json").symlink_to(self.repo / "hello.py")
        with self.assertRaises(ValueError):
            conversation(self.run)
        (self.run / "plan.json").unlink()
        (self.run / "plan.json").write_text(json.dumps(dict(summary="x" * 256001)))
        with self.assertRaisesRegex(ValueError, "256 KB"):
            conversation(self.run)

    def test_stop_running_worker_then_resume_same_run(self):
        self.configure("planner-timeout")
        result = self.launcher.submit(self.payload)
        run = self.runs / result["id"]
        self.wait_for(lambda: (run / "01-plan/stderr.log").exists())
        stopped = self.launcher.action(dict(id=run.name, action="stop"))
        self.assertEqual(stopped["status"], "STOP_REQUESTED")
        self.launcher.workers[run][0].wait(timeout=10)
        self.assertEqual(json.loads((run / "run.json").read_text())["status"], "INTERRUPTED")
        self.assertTrue((run / "checkpoint.json").is_file())
        self.assertEqual((self.repo / "hello.py").read_text(), "def hello():\n    return 1\n")
        self.assertTrue(run_view(self.runs, run.name)["actions"]["resume"])
        self.configure("ok")
        continued = self.launcher.action(dict(id=run.name, action="resume"))
        self.assertEqual(continued["id"], run.name)
        self.launcher.workers[run][0].wait(timeout=15)
        self.assertEqual(
            json.loads((run / "run.json").read_text())["status"],
            "READY_FOR_REVIEW",
            (run / "report.md").read_text()
            + "\n"
            + "\n".join(p.read_text() for p in run.glob("*/stderr.log")),
        )
        self.assertFalse((run / "stop.request").exists())
        self.assertIn("return 2", (self.repo / "hello.py").read_text())

    def test_answer_only_rejects_model_changes_before_writer(self):
        with patch.object(self.launcher, "launch") as launch:
            self.launcher.submit(dict(self.payload, read_only=True))
        task = self.base / "answer.md"
        task.write_text(launch.call_args.args[0]["text"])
        run, status = execute_task(task, self.settings, run_dir=self.runs / "answer")
        self.assertEqual(status, "INVALID_RESULT")
        stages = json.loads((run / "run.json").read_text())["stages"]
        self.assertFalse(any(stage["stage"] == "implementer" for stage in stages))
        self.assertIn("return 1", (self.repo / "hello.py").read_text())

    def test_answer_only_completes_with_independent_review(self):
        self.configure("no-change")
        with patch.object(self.launcher, "launch") as launch:
            self.launcher.submit(dict(self.payload, read_only=True))
        task = self.base / "answer.md"
        task.write_text(launch.call_args.args[0]["text"])
        run, status = execute_task(task, self.settings, run_dir=self.runs / "answer")
        self.assertEqual(status, "NO_CHANGES_REQUIRED")
        stages = json.loads((run / "run.json").read_text())["stages"]
        self.assertEqual([stage["stage"] for stage in stages], ["planner", "plan-reviewer"])
