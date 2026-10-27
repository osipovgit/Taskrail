"""Task lifecycle controls, history isolation and answer-only execution."""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.application import mode_rules
from taskrail.application.live import execute_task
from taskrail.core.files import atomic_json
from taskrail.web import delivery_launch, requests, submissions, task_form
from taskrail.web.history import HISTORY, TaskDraft, conversation, previous_messages, task_draft
from taskrail.web.lifecycle import trash_run
from taskrail.web.run_list import list_runs
from taskrail.web.run_view import run_view
from taskrail.web.submissions import TaskLauncher
from taskrail.web.task_form import build_task

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
                    agent_source=str(BASE / "taskrail/agents"),
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
        meta = json.loads(text.split("```taskrail-task\n")[1].split("```")[0])
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

    def test_only_a_server_check_names_its_confirmed_change(self):
        for fields in (
            dict(phase="validation", confirmed_change="original"),
            dict(confirmed_change="original"),
            dict(phase="server", confirmed_change="../original"),
        ):
            with (
                self.subTest(fields=fields),
                self.assertRaisesRegex(ValueError, "Only a server check"),
            ):
                self.launcher.submit(dict(self.payload, **fields))

    def test_worktree_flag_is_a_boolean_task_header_option(self):
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(dict(self.payload, worktree=True, read_only=True))
            text = launch.call_args.args[0]["text"]
        meta = json.loads(text.split("```taskrail-task\n")[1].split("```")[0])
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
        meta = json.loads(text.split("```taskrail-task\n")[1].split("```")[0])
        self.assertIs(meta["auto_approve"], True)
        (self.run / "00-input/task.md").write_text(text)
        self.assertTrue(task_draft(self.run)["auto_approve"])
        with self.assertRaisesRegex(ValueError, "boolean"):
            self.launcher.submit(dict(self.payload, auto_approve="yes"))

    def test_design_discussion_is_read_only_and_asks_for_a_document(self):
        with patch.object(self.launcher, "launch", return_value={"id": "next"}) as launch:
            self.launcher.submit(dict(self.payload, design=True))
            text = launch.call_args.args[0]["text"]
        meta = json.loads(text.split("```taskrail-task\n")[1].split("```")[0])
        self.assertTrue(meta["design"])
        self.assertTrue(meta["read_only"])
        self.assertNotIn("Turn control", text)
        rule = mode_rules.render(dict(design=True, read_only=True), "planner")
        self.assertIn("Mode: design discussion. Change nothing", rule)
        self.assertNotIn("answer only", rule)
        self.assertIn("Mode: split into tasks", mode_rules.render(dict(decompose=True), "planner"))
        self.assertIn("this run then implements it", mode_rules.render({}, "planner"))
        self.assertEqual(mode_rules.render({}, "implementer"), "")
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

    def test_restart_drafts_keep_policy_separate_and_preserve_explicit_user_text(self):
        draft = task_draft(self.run)
        self.assertNotIn("Workflow rules", draft["constraints"])
        edited = dict(draft, constraints="Keep X\n\n### Workflow rules\nMy own rule")
        fields = {key: edited[key] for key in task_form.FIELDS}
        text, _ = build_task(dict(fields, roots=edited["roots"]), self.runs)
        self.assertEqual(TaskDraft(text).fields()["constraints"], edited["constraints"])
        self.assertEqual(sum(line == "## Workflow rules" for line in text.splitlines()), 1)
        self.assertIn("## Additional constraints\nKeep X\n", text)

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
            requirements=[],
        )
        (epic / "run.json").write_text(json.dumps(index))
        (epic / "00-input/settings.json").write_text("{}")
        return epic

    def launching(self, name):
        """Stub the worker start; like a real launch, the parent links the run first."""

        def launch(request, sources):
            if request.get("before_start"):
                request["before_start"](name)
            return {"id": name}

        return patch.object(self.launcher, "launch", side_effect=launch)

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
        view = run_view(self.runs, "epic")["delivery"]
        self.assertEqual(view["next"], "S-1")
        with self.launching("child-1") as launch:
            self.launcher.action(dict(id="epic", action="epic_next"))
            text = launch.call_args.args[0]["text"]
        self.assertIn("Change hello: return 2", text)
        self.assertIn("S-1: Change hello (current task)", text)
        self.assertNotIn("S-2: Document hello", text)
        snapshot = launch.call_args.args[0]["parent_context"]
        self.assertIn("Document hello", snapshot)
        self.assertIn('"auto_approve": true', text)
        self.assertNotIn('"decompose"', text)
        self.assertNotIn("Conversation history", text)
        ids = [entry["text"] for entry in TaskDraft(text).typed["requirements"]]
        self.assertFalse(any("S-2" in entry or "Workflow rules" in entry for entry in ids))
        self.assertIn("## Task split context", text)
        self.assertIn(self.payload["criteria"], snapshot)
        self.assertIn("parent-task.md", text)
        self.assertIn("## Acceptance criteria\n- hello returns 2", text)
        self.assertEqual(json.loads((epic / "epic.json").read_text())["tasks"], {"S-1": "child-1"})
        with self.assertRaisesRegex(ValueError, "No task is ready"):
            self.launcher.action(dict(id="epic", action="epic_next"))
        self.finish("child-1", "TOOL_ERROR")
        self.assertEqual(run_view(self.runs, "epic")["delivery"]["next"], "S-1")
        epic_entry = next(run for run in list_runs(self.runs) if run["id"] == "epic")
        self.assertEqual(epic_entry["group"], "attention")
        self.launcher.action(dict(id="epic", action="epic_auto_on"))
        with patch.object(self.launcher, "launch") as launch:
            delivery_launch.advance(self.launcher)
        launch.assert_not_called()
        self.launcher.action(dict(id="child-1", action="done"))
        self.assertEqual(run_view(self.runs, "epic")["delivery"]["next"], "S-2")
        self.launcher.action(dict(id="child-1", action="reopen"))
        self.launcher.action(dict(id="epic", action="revoke_auto_approve"))
        with self.launching("child-1b") as launch:
            self.launcher.action(dict(id="epic", action="epic_next"))
            text = launch.call_args.args[0]["text"]
        self.assertNotIn('"auto_approve"', text)
        self.assertEqual(json.loads((epic / "epic.json").read_text())["tasks"]["S-1"], "child-1b")
        self.finish("child-1b", "TOOL_ERROR")
        self.finish("child-1b", "READY_FOR_REVIEW")
        self.launcher.action(dict(id="epic", action="epic_pause", task="S-2"))
        self.assertTrue(run_view(self.runs, "epic")["delivery"]["tasks"][1]["pause_before"])
        with patch.object(self.launcher, "launch") as launch:
            delivery_launch.advance(self.launcher)
        launch.assert_not_called()
        epic_entry = next(run for run in list_runs(self.runs) if run["id"] == "epic")
        self.assertEqual(epic_entry["group"], "attention")
        with self.assertRaisesRegex(ValueError, "task of the split"):
            self.launcher.action(dict(id="epic", action="epic_pause", task="../x"))
        self.launcher.action(dict(id="epic", action="epic_unpause", task="S-2"))
        with self.launching("child-2") as launch:
            delivery_launch.advance(self.launcher)
            text = launch.call_args.args[0]["text"]
        self.assertIn("S-1: Change hello (READY_FOR_REVIEW): child-1b summary", text)
        self.finish("child-2", "READY_FOR_REVIEW")
        epic_entry = next(run for run in list_runs(self.runs) if run["id"] == "epic")
        self.assertEqual((epic_entry["group"], epic_entry["progress"]), ("running", "2/2"))

    def test_a_running_or_waiting_task_keeps_auto_continue_and_shows_the_right_group(self):
        epic = self.make_epic()
        self.launcher.action(dict(id="epic", action="epic_auto_on"))
        with self.launching("child-1"):
            delivery_launch.advance(self.launcher)
        self.finish("child-1", "RUNNING")

        def unchanged_by_service_ticks():
            with patch.object(self.launcher, "launch") as launch:
                delivery_launch.advance(self.launcher)
                delivery_launch.advance(self.launcher)
            launch.assert_not_called()
            record = json.loads((epic / "epic.json").read_text())
            self.assertTrue(record["auto_continue"])
            self.assertNotIn("launch_error", record)

        unchanged_by_service_ticks()
        entry = next(run for run in list_runs(self.runs) if run["id"] == "epic")
        self.assertEqual(entry["group"], "running")
        self.assertEqual(run_view(self.runs, "epic")["delivery"]["step"], "implementing")
        request = dict(status="LOCAL_REQUEST", argv=["make"], cwd=str(self.repo))
        atomic_json(self.runs / "child-1/pending-approval.json", dict(ticket="t", request=request))
        unchanged_by_service_ticks()
        delivery = run_view(self.runs, "epic")["delivery"]
        self.assertEqual((delivery["next"], delivery["step"]), (None, "needs_you"))
        entry = next(run for run in list_runs(self.runs) if run["id"] == "epic")
        self.assertEqual(entry["group"], "attention")

    def test_allow_all_given_in_a_task_run_covers_the_whole_split(self):
        epic = self.make_epic()
        task = (epic / "00-input/task.md").read_text()
        (epic / "00-input/task.md").write_text(task.replace('"auto_approve": true, ', ""))
        with self.launching("child-1") as launch:
            self.launcher.action(dict(id="epic", action="epic_next"))
        first = launch.call_args.args[0]["text"]
        self.assertNotIn('"auto_approve"', first)
        child = self.runs / "child-1"
        (child / "00-input").mkdir(parents=True)
        (child / "00-input/task.md").write_text(first)
        state = dict(status="RUNNING", summary="", roots={"project": str(self.repo)}, stages=[])
        (child / "run.json").write_text(json.dumps(state))
        request = dict(status="LOCAL_REQUEST", argv=["make"], cwd=str(self.repo))
        atomic_json(child / "pending-approval.json", dict(ticket="t1", request=request))
        decision = dict(id="child-1", ticket="t1", decision="allow", alternative="", allow_all=True)
        self.launcher.route("/api/decision", decision)
        self.assertTrue(run_view(self.runs, "epic")["auto_approve"])
        (child / "pending-approval.json").unlink()
        self.finish("child-1", "READY_FOR_REVIEW")
        (child / "00-input/task.md").write_text(first)
        with self.launching("child-2") as launch:
            self.launcher.action(dict(id="epic", action="epic_next"))
        self.assertIn('"auto_approve": true', launch.call_args.args[0]["text"])
        self.launcher.action(dict(id="child-1", action="revoke_auto_approve"))
        self.assertFalse(run_view(self.runs, "epic")["auto_approve"])
        self.assertTrue((epic / "auto-approve.off").exists())

    def test_split_requires_independent_combined_review_and_fresh_source(self):
        epic = self.make_epic()
        plan = json.loads((epic / "plan.json").read_text())
        plan["unverified"] = ["Server check: health returns 200"]
        (epic / "plan.json").write_text(json.dumps(plan))
        with self.launching("child-1"):
            self.launcher.action(dict(id="epic", action="epic_next"))
        self.finish("child-1", "READY_FOR_REVIEW")
        with self.launching("child-2"):
            self.launcher.action(dict(id="epic", action="epic_next"))
        self.finish("child-2", "READY_FOR_REVIEW")
        self.assertEqual(run_view(self.runs, "epic")["delivery"]["step"], "integrating")
        with self.assertRaisesRegex(ValueError, "waits for confirmation"):
            self.launcher.action(dict(id="epic", action="confirm"))
        with self.launching("integrated") as launch:
            delivery_launch.advance(self.launcher)
            delivery_launch.advance(self.launcher)
        self.assertEqual(launch.call_count, 1)
        submitted = launch.call_args.args[0]
        self.assertIn('"phase": "integration"', submitted["text"])
        self.assertIn("Return 2 and document it", submitted["text"])
        self.assertIn(self.payload["criteria"], submitted["text"])
        self.assertIn('"read_only": true', submitted["text"])
        self.configure("no-change")
        task = self.base / "integration.md"
        task.write_text(submitted["text"])
        (self.base / "parent-task.md").write_text(submitted["parent_context"])
        run, status = execute_task(task, self.settings, run_dir=self.runs / "integrated")
        self.assertEqual(status, "NO_CHANGES_REQUIRED")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual([record["stage"] for record in state["stages"]], ["reviewer"])
        self.assertEqual(run_view(self.runs, "epic")["delivery"]["step"], "confirm")
        source = self.repo / "hello.py"
        original = source.read_text()
        source.write_text("changed after review\n")
        with self.assertRaisesRegex(ValueError, "Source changed since integration"):
            self.launcher.action(dict(id="epic", action="confirm"))
        source.write_text(original)
        with patch.object(delivery_launch, "executor_offers", return_value={}):
            self.launcher.action(dict(id="epic", action="confirm"))
        self.assertEqual(run_view(self.runs, "epic")["delivery"]["step"], "done")
        self.finish("child-2", "TOOL_ERROR")
        self.assertEqual(run_view(self.runs, "epic")["delivery"]["step"], "needs_you")

    def test_repeat_review_keeps_active_phases_and_archives_stopped_links(self):
        epic = self.make_epic()
        for name in ("child-1", "child-2"):
            self.finish(name, "READY_FOR_REVIEW")
        self.finish("old-review", "NO_CHANGES_REQUIRED")
        self.finish("old-validation", "RUNNING")
        phases = dict(integration="old-review", validation="old-validation")
        record = dict(tasks={"S-1": "child-1", "S-2": "child-2"}, phases=phases, confirmed=1)
        atomic_json(epic / "epic.json", record)
        with self.assertRaisesRegex(ValueError, "Stop active delivery phases"):
            self.launcher.action(dict(id="epic", action="integration_review"))
        self.assertEqual(json.loads((epic / "epic.json").read_text()), record)
        self.finish("old-validation", "TOOL_ERROR")
        with self.launching("new-review"):
            self.launcher.action(dict(id="epic", action="integration_review"))
        updated = json.loads((epic / "epic.json").read_text())
        self.assertEqual(updated["phases"], dict(integration="new-review"))
        self.assertEqual(updated["phase_history"], [phases])
        self.assertNotIn("confirmed", updated)

    def test_invalid_child_submission_pauses_automatic_launch_visibly(self):
        epic = self.make_epic()
        self.launcher.action(dict(id="epic", action="epic_auto_on"))
        with patch.object(self.launcher, "submit", side_effect=ValueError("Contract too large")):
            delivery_launch.proceed(self.launcher, epic)
        view = run_view(self.runs, "epic")["delivery"]
        self.assertEqual(view["launch_error"], "Contract too large")
        self.assertEqual(view["step"], "needs_you")
        self.assertFalse(view["auto_continue"])
        with patch.object(self.launcher, "submit") as submit:
            delivery_launch.proceed(self.launcher, epic)
        submit.assert_not_called()

    def test_a_task_run_is_linked_before_its_worker_and_never_started_twice(self):
        epic = self.make_epic()
        record = epic / "epic.json"

        def application_stops(*arguments):
            self.assertIn("S-1", json.loads(record.read_text())["tasks"])
            raise KeyboardInterrupt

        with (
            patch.object(submissions, "start_worker", side_effect=application_stops),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.launcher.action(dict(id="epic", action="epic_next"))
        child = json.loads(record.read_text())["tasks"]["S-1"]
        launch = self.runs / ".submissions" / child / "launch.json"
        self.assertEqual(json.loads(launch.read_text())["status"], "STARTING")
        restarted = TaskLauncher(self.runs, self.settings)
        self.assertEqual(json.loads(launch.read_text())["status"], "LAUNCH_ERROR")
        self.assertEqual(
            run_view(self.runs, "epic")["delivery"]["tasks"][0]["status"], "LAUNCH_ERROR"
        )
        restarted.action(dict(id="epic", action="epic_auto_on"))
        with patch.object(restarted, "launch") as launch_again:
            delivery_launch.advance(restarted)
        launch_again.assert_not_called()

    def test_a_started_worker_survives_a_restart_without_a_second_run(self):
        epic = self.make_epic()
        self.launcher.action(dict(id="epic", action="epic_auto_on"))

        def worker_starts(folder, manifest, run, options):
            atomic_json(folder / "launch.json", dict(manifest, status="RUNNING", pid=1))

        with patch.object(submissions, "start_worker", side_effect=worker_starts):
            started = self.launcher.action(dict(id="epic", action="epic_next"))
        restarted = TaskLauncher(self.runs, self.settings)
        launch = self.runs / ".submissions" / started["id"] / "launch.json"
        self.assertEqual(json.loads(launch.read_text())["status"], "RUNNING")
        self.assertEqual(
            json.loads((epic / "epic.json").read_text())["tasks"], {"S-1": started["id"]}
        )
        with patch.object(restarted, "launch") as launch_again:
            delivery_launch.advance(restarted)
        launch_again.assert_not_called()

    def test_a_pause_set_while_a_task_starts_is_kept(self):
        epic = self.make_epic()
        starting, release = threading.Event(), threading.Event()

        def slow_start(*arguments):
            starting.set()
            release.wait(5)

        def act(payload):
            return threading.Thread(target=self.launcher.action, args=(payload,))

        with patch.object(submissions, "start_worker", side_effect=slow_start):
            start = act(dict(id="epic", action="epic_next"))
            start.start()
            self.assertTrue(starting.wait(5))
            pause = act(dict(id="epic", action="epic_pause", task="S-2"))
            pause.start()
            pause.join(0.3)
            self.assertTrue(pause.is_alive())
            release.set()
            start.join(5)
            pause.join(5)
        record = json.loads((epic / "epic.json").read_text())
        self.assertEqual(list(record["tasks"]), ["S-1"])
        self.assertEqual(record["pause_before"], ["S-2"])

    def test_delivery_validates_waits_for_confirmation_then_checks_servers(self):
        unverified = [
            "Jenkins check: ci/shop-tests: passes",
            "Server check: health returns 200",
            "Lint only",
        ]
        (self.run / "plan.json").write_text(
            json.dumps(dict(status="PLAN_READY", unverified=unverified))
        )
        (self.run / "run.json").write_text(
            json.dumps(
                dict(
                    json.loads((self.run / "run.json").read_text()),
                    changed_files=["/repo/hello.py"],
                )
            )
        )
        offers = dict(jenkins={"ci": {}}, hosts={"web": {}})

        def delivery():
            return run_view(self.runs, "original")["delivery"]

        self.assertEqual(
            delivery()["checks"],
            dict(jenkins=["ci/shop-tests: passes"], server=["health returns 200"]),
        )
        self.assertEqual(delivery()["step"], "validating")
        with self.assertRaisesRegex(ValueError, "waits for confirmation"):
            self.launcher.action(dict(id="original", action="confirm"))
        with (
            patch.object(delivery_launch, "executor_offers", return_value=offers),
            self.launching("validation-1") as launch,
        ):
            delivery_launch.advance(self.launcher)
            delivery_launch.advance(self.launcher)
        self.assertEqual(launch.call_count, 1)
        text = launch.call_args.args[0]["text"]
        self.assertIn('"phase": "validation"', text)
        self.assertNotIn("confirmed_change", text)
        self.assertIn('"read_only": true', text)
        self.assertIn('"ci/shop-tests: passes"', text)
        self.assertIn("Changed files: /repo/hello.py", text)
        self.finish("validation-1", "NO_CHANGES_REQUIRED")
        self.assertEqual(delivery()["step"], "confirm")
        entry = next(run for run in list_runs(self.runs) if run["id"] == "original")
        self.assertEqual(entry["group"], "review")
        with (
            patch.object(delivery_launch, "executor_offers", return_value=offers),
            self.launching("server-1") as launch,
        ):
            self.launcher.action(dict(id="original", action="confirm"))
        text = launch.call_args.args[0]["text"]
        metadata = TaskDraft(text).metadata
        self.assertEqual(metadata["phase"], "server")
        self.assertEqual(metadata["confirmed_change"], "original")
        self.assertIn('"health returns 200"', text)
        self.assertEqual(delivery()["step"], "server")
        self.finish("server-1", "RUNNING")
        waiting = json.loads((self.runs / "server-1/run.json").read_text())
        waiting["execution_jobs"] = [dict(status="PENDING_APPROVAL")]
        (self.runs / "server-1/run.json").write_text(json.dumps(waiting))
        self.assertEqual(delivery()["step"], "approval")
        entry = next(run for run in list_runs(self.runs) if run["id"] == "original")
        self.assertEqual(entry["group"], "attention")
        self.finish("server-1", "READY_FOR_REVIEW")
        self.assertEqual(delivery()["step"], "done")

    def phase_run(self, name, phase, status):
        """A finished phase run whose task names its delivery, like a launched one."""
        header = dict(phase=phase, check_parent="original", roots={"project": str(self.repo)})
        child = self.runs / name
        (child / "00-input").mkdir(parents=True, exist_ok=True)
        task = f"```taskrail-task\n{json.dumps(header)}\n```\n# {phase}\n"
        (child / "00-input/task.md").write_text(task)
        state = dict(status=status, summary=f"{name} failed\ndetails", phase=phase, stages=[])
        state["roots"] = header["roots"]
        (child / "run.json").write_text(json.dumps(state))

    def test_a_restarted_phase_stays_in_its_delivery_with_earlier_attempts(self):
        (self.run / "plan.json").write_text(
            json.dumps(dict(status="PLAN_READY", unverified=["Jenkins check: ci/tests: passes"]))
        )
        offers = dict(jenkins={"ci": {}})
        with (
            patch.object(delivery_launch, "executor_offers", return_value=offers),
            self.launching("validation-1"),
        ):
            delivery_launch.advance(self.launcher)
        self.phase_run("validation-1", "validation", "TOOL_ERROR")
        self.assertEqual(run_view(self.runs, "original")["delivery"]["step"], "validation_failed")
        listed = {run["id"]: run for run in list_runs(self.runs)}
        self.assertNotIn("validation-1", listed)
        self.assertEqual(listed["original"]["members"], ["validation-1"])
        failed = run_view(self.runs, "validation-1")
        self.assertEqual(failed["parent"], dict(run="original", slot="validation"))
        self.assertFalse(failed["actions"]["followup"])
        with (
            patch.object(delivery_launch, "executor_offers", return_value=offers),
            self.launching("validation-2") as launch,
        ):
            result = self.launcher.action(dict(id="validation-1", action="restart"))
        self.assertEqual(result["id"], "validation-2")
        self.assertIn('"phase": "validation"', launch.call_args.args[0]["text"])
        record = json.loads((self.run / "epic.json").read_text())
        self.assertEqual(record["phases"], dict(validation="validation-2"))
        self.assertEqual(
            record["phase_attempts"], dict(validation=["validation-1", "validation-2"])
        )
        self.phase_run("validation-2", "validation", "RUNNING")
        phase = run_view(self.runs, "original")["delivery"]["phases"]["validation"]
        self.assertEqual(phase["run"], "validation-2")
        self.assertEqual(
            phase["attempts"],
            [dict(run="validation-1", status="TOOL_ERROR", reason="validation-1 failed")],
        )
        with self.assertRaisesRegex(ValueError, "latest attempt"):
            self.launcher.action(dict(id="validation-1", action="restart"))
        with self.assertRaisesRegex(ValueError, "Stop the phase"):
            self.launcher.action(dict(id="validation-2", action="restart"))
        with self.assertRaisesRegex(ValueError, "belongs to a split or delivery"):
            requests.Submission(
                dict(self.payload, parent_run="validation-2", submission_mode="followup"),
                self.runs,
            )

    def test_delivery_phases_are_skipped_without_an_executor_and_wait_when_unreachable(self):
        unverified = ["Jenkins check: ci/tests: passes"]
        (self.run / "plan.json").write_text(
            json.dumps(dict(status="PLAN_READY", unverified=unverified))
        )
        with patch.object(delivery_launch, "executor_offers", return_value=None):
            delivery_launch.advance(self.launcher)
        self.assertNotIn(
            "phases",
            json.loads((self.run / "epic.json").read_text())
            if (self.run / "epic.json").exists()
            else {},
        )
        with patch.object(delivery_launch, "executor_offers", return_value={}):
            delivery_launch.advance(self.launcher)
        view = run_view(self.runs, "original")["delivery"]
        self.assertEqual(view["phases"]["validation"]["status"], "skipped")
        # Without server checks nothing changes servers: no confirmation, only your review.
        self.assertEqual(view["step"], "review")
        entry = next(run for run in list_runs(self.runs) if run["id"] == "original")
        self.assertEqual(entry["group"], "review")
        with self.assertRaisesRegex(ValueError, "waits for confirmation"):
            self.launcher.action(dict(id="original", action="confirm"))
        self.launcher.action(dict(id="original", action="done"))
        entry = next(run for run in list_runs(self.runs) if run["id"] == "original")
        self.assertEqual(entry["group"], "done")

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
        self.assertEqual(list_runs(self.runs)[0]["mode"], "develop")
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
