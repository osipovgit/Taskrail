"""Delivery authorization regressions using real records and shared CLI/API workflows."""

import contextlib
import io
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_prompt_contract import CAPABILITIES, assert_request_budget

from taskrail import cli
from taskrail.application import (
    check_parents,
    check_remote,
    delivery_confirmation,
    execution_requests,
    execution_wait,
    prompts,
    task_config,
)
from taskrail.application.source_guard import SourceGuard
from taskrail.core import approval_marks, delivery_record, prompt_texts
from taskrail.core.files import atomic_json
from taskrail.interactions import approval_policy, approvals, jenkins
from taskrail.web import delivery_launch, epic_record, requests, split_approvals, task_form
from taskrail.web.submissions import TaskLauncher


class DeliveryApprovalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.runs = self.base / "runs"
        self.runs.mkdir()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / "app.py").write_text("answer = 42\n")
        (self.repo / ".git").mkdir()
        (self.repo / ".git/HEAD").write_text("ref: refs/heads/main\n")
        self.parent = self.make_run("parent")
        self.launcher = TaskLauncher(self.runs, recover=False)
        self.request = dict(status="LOCAL_REQUEST", argv=["make"], cwd=str(self.repo))

    def make_run(self, name, **metadata):
        run = self.runs / name
        (run / "00-input").mkdir(parents=True)
        payload = dict(
            goal="Return the reviewed result",
            criteria="Keep existing behavior",
            roots=[dict(alias="project", path=str(self.repo))],
            auto_approve=True,
            **metadata,
        )
        submission = requests.Submission(payload, self.runs)
        text, _ = task_form.build_task(submission.fields, self.runs)
        (run / "00-input/task.md").write_text(submission.decorate(text))
        state = dict(
            status="READY_FOR_REVIEW",
            roots={"project": str(self.repo)},
            results={"plan": "plan.json"},
            stages=[],
            requirements=[],
            auto_approve=True,
        )
        atomic_json(run / "run.json", state)
        atomic_json(run / "plan.json", dict(unverified=["Server check: inspect the service"]))
        boundary = SourceGuard({"project": self.repo})
        boundary.capture()
        atomic_json(
            run / "checkpoint.json",
            dict(expected=boundary.expected, git_before=boundary.git_before),
        )
        return run

    def family(self):
        # Phase metadata exercises the same membership route as split task contracts.
        for name in ("old", "current", "phase"):
            self.make_run(name, phase="validation", check_parent="parent")
        self.make_run("unrelated")
        record = dict(
            auto_approve=True,
            tasks={"S-1": "current", "S-2": "pending"},
            attempts={"S-1": ["old", "current"]},
            phases={"validation": "phase"},
        )
        atomic_json(self.parent / "epic.json", record)

    def action(self, name, action, route):
        if route == "api":
            return self.launcher.route("/api/actions", dict(id=name, action=action))
        output = io.StringIO()
        args = ["taskrail", "action", name, action, "--runs-dir", str(self.runs)]
        with patch("sys.argv", args), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(), 0)
        return json.loads(output.getvalue())

    def test_revoke_parent_current_or_old_attempt_covers_existing_and_pending_workers(self):
        self.family()
        for origin in ("parent", "current", "old"):
            for route in ("api", "cli"):
                with self.subTest(origin=origin, route=route):
                    answer = self.action(origin, "revoke_auto_approve", route)
                    self.assertEqual(answer["status"], "AUTO_APPROVE_REVOKED")
                    for name in ("parent", "old", "current", "phase", "pending"):
                        run = self.runs / name
                        state = dict(auto_approve=True)
                        self.assertFalse(approval_policy.enabled(run, state))
                        self.assertFalse(approval_policy.at_start(run, dict(auto_approve=True)))
                    self.assertTrue(
                        approval_policy.enabled(self.runs / "unrelated", dict(auto_approve=True))
                    )
                    for name in ("parent", "old", "current", "phase", "pending"):
                        approval_marks.grant(self.runs / name)

    def test_pending_worker_stays_revoked_after_parent_disappears(self):
        self.family()
        self.action("old", "revoke_auto_approve", "api")
        shutil.rmtree(self.parent)
        pending = self.make_run("pending")
        self.assertFalse(approval_policy.at_start(pending, dict(auto_approve=True)))
        state = dict(auto_approve=True)
        with patch.object(approvals, "wait", return_value=dict(decision="deny")) as wait:
            approval_policy.decision(self.runs / "current", self.request, state)
        wait.assert_called_once()

    def test_revoke_serializes_with_a_link_before_its_worker_exists(self):
        linked = threading.Event()
        finished = threading.Event()

        def revoke():
            linked.set()
            split_approvals.revoke(self.parent)
            finished.set()

        with epic_record.changing(self.parent) as record:
            thread = threading.Thread(target=revoke)
            thread.start()
            self.assertTrue(linked.wait(2))
            self.assertFalse(finished.is_set())
            epic_record.link(self.parent, record, ("tasks", "S-1"), "pending")
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(finished.is_set())
        self.assertFalse(approval_policy.at_start(self.runs / "pending", dict(auto_approve=True)))

    def test_delayed_allow_all_answer_cannot_clear_a_newer_revoke(self):
        self.family()
        run = self.runs / "current"
        state = dict(auto_approve=False)
        answer = dict(id="current", ticket="t", decision="allow", alternative="", allow_all=True)

        def delayed_reply(run, request):
            atomic_json(run / approvals.PENDING, dict(ticket="t", request=request))
            self.launcher.route("/api/decision", answer)
            self.action("old", "revoke_auto_approve", "api")
            return answer

        with patch.object(approvals, "wait", side_effect=delayed_reply):
            self.assertEqual(approval_policy.decision(run, self.request, state), answer)
        self.assertFalse(approval_policy.enabled(run, state))
        self.assertFalse(split_approvals.shown(self.parent, dict(auto_approve=True)))

    def test_fresh_personal_grant_restores_only_that_worker_and_future_children(self):
        self.family()
        self.action("old", "revoke_auto_approve", "api")
        run = self.runs / "current"
        answer = dict(id="current", ticket="t", decision="allow", alternative="", allow_all=True)
        atomic_json(run / approvals.PENDING, dict(ticket="t", request=self.request))
        self.launcher.route("/api/decision", answer)
        self.assertTrue(approval_policy.at_start(run, dict(auto_approve=True)))
        self.assertTrue(split_approvals.allows_all(self.parent, dict(auto_approve=True)))
        self.assertFalse(approval_policy.at_start(self.runs / "old", dict(auto_approve=True)))

    def confirm(self, route="api"):
        with patch.object(delivery_launch, "executor_offers", return_value=None):
            return self.action("parent", "confirm", route)

    def test_unchanged_confirmation_is_valid_from_cli_and_api(self):
        for route in ("api", "cli"):
            with self.subTest(route=route):
                (self.parent / "epic.json").unlink(missing_ok=True)
                self.assertEqual(self.confirm(route)["status"], "CONFIRMED")
                delivery_confirmation.verify(self.parent)

    def test_confirmed_server_prompts_use_real_confirmation_and_stay_within_budget(self):
        self.assertEqual(self.confirm()["status"], "CONFIRMED")
        run = self.make_run(
            "server", phase="server", confirmed_change="parent", check_parent="parent"
        )
        with epic_record.changing(self.parent) as record:
            record["phases"] = dict(server=run.name)
        settings = self.base / "settings.json"
        atomic_json(settings, dict(opencode_version="1.x"))
        config = task_config.configuration(run / "00-input/task.md", settings)
        state = json.loads((run / "run.json").read_text())
        state.update(
            checks=[],
            preimages={},
            requirements=config["task_spec"]["requirements"],
            contract_version=1,
        )
        for stage in ("planner", "reviewer"):
            with (
                self.subTest(stage=stage),
                patch.object(execution_requests, "available", return_value=CAPABILITIES),
            ):
                self.assertEqual(execution_requests.remote_mode(run, config, stage), "server")
                request = prompts.make_request(config, (stage, None, [], None), state, run)
            self.assertIn(prompt_texts.text("routes.ssh.server"), request)
            self.assertIn('"status":{"const":"ACTION_REQUEST"}', request)
            self.assertIn('"status":{"const":"JENKINS_REQUEST"}', request)
            assert_request_budget(self, request, stage, self.base)
        (self.repo / "app.py").write_text("changed after confirmation\n")
        with (
            patch.object(execution_requests, "available", return_value=CAPABILITIES),
            self.assertRaisesRegex(ValueError, "Confirmed"),
        ):
            prompts.make_request(config, ("reviewer", None, [], None), state, run)

    def test_standalone_confirmation_rejects_source_and_git_drift(self):
        for relative in ("app.py", ".git/HEAD"):
            path = self.repo / relative
            original = path.read_text()
            path.write_text("outside change\n")
            with self.subTest(path=relative), self.assertRaisesRegex(ValueError, "Source changed"):
                self.confirm()
            self.assertFalse(delivery_record.read(self.parent).get("confirmed"))
            path.write_text(original)

    def test_server_launch_and_each_action_recheck_confirmed_source_git_and_evidence(self):
        self.confirm()
        cases = (self.repo / "app.py", self.repo / ".git/HEAD", self.parent / "plan.json")
        for path in cases:
            original = path.read_text()
            path.write_text("outside change\n")
            with (
                self.subTest(path=path.name),
                patch.object(
                    delivery_launch, "executor_offers", return_value=dict(hosts={"web": {}})
                ),
                patch.object(self.launcher, "submit") as submit,
                self.assertRaisesRegex(ValueError, "Confirmed source/Git"),
            ):
                delivery_launch.start_phase(self.launcher, self.parent, "server")
            submit.assert_not_called()
            path.write_text(original)
        with epic_record.changing(self.parent) as record:
            record["phases"] = dict(server="server")
        run = self.runs / "server"
        config = dict(phase="server", confirmed_change="parent")
        self.assertEqual(execution_requests.remote_mode(run, config, "reviewer"), "server")
        for path in cases:
            original = path.read_text()
            path.write_text("outside change\n")
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, "Confirmed"):
                execution_requests.remote_mode(run, config, "reviewer")
            path.write_text(original)

    def test_legacy_confirmation_without_fingerprints_cannot_authorize_server_actions(self):
        atomic_json(self.parent / "epic.json", dict(confirmed=1, phases=dict(server="server")))
        with self.assertRaisesRegex(ValueError, "review and confirmation"):
            execution_requests.remote_mode(
                self.runs / "server", dict(phase="server", confirmed_change="parent"), "reviewer"
            )

    def test_server_start_and_resume_recheck_before_adopting_parent_evidence(self):
        self.confirm()
        with epic_record.changing(self.parent) as record:
            record["phases"] = dict(server="server")
        workflow = SimpleNamespace(
            run=self.runs / "server", config=dict(phase="server", check_parent="parent")
        )
        (self.repo / "app.py").write_text("outside change after phase launch\n")
        for resume in (False, True):
            with self.subTest(resume=resume), self.assertRaisesRegex(ValueError, "Confirmed"):
                check_parents.adopt(workflow, resume=resume)

    def test_server_jenkins_and_ssh_recipes_recheck_evidence_before_submitting(self):
        self.confirm()
        with epic_record.changing(self.parent) as record:
            record["phases"] = dict(server="server")
        guard = SourceGuard({"project": self.repo})
        guard.capture()
        workflow = SimpleNamespace(
            run=self.runs / "server",
            config=dict(phase="server", confirmed_change="parent"),
            guard=guard,
        )
        (self.parent / "plan.json").write_text('{"changed":true}')
        for kind in ("jenkins", "ssh"):
            with (
                self.subTest(kind=kind),
                patch.object(check_remote, "followed") as followed,
                self.assertRaisesRegex(ValueError, "Confirmed"),
            ):
                check_remote.execute(workflow, workflow.run, {}, dict(kind=kind))
            followed.assert_not_called()

    def test_confirmation_rejects_parent_or_child_root_maps_that_differ_from_review(self):
        integrated = self.make_run("integrated", phase="integration", check_parent="parent")
        child = self.make_run(
            "child", phase="task", assigned_contract=dict(parent_run="parent", task_id="S1")
        )
        record = dict(tasks={"S1": child.name}, phases=dict(integration=integrated.name))
        for member in (self.parent, child):
            with self.subTest(member=member.name):
                state_path = member / "run.json"
                original = state_path.read_text()
                state = json.loads(original)
                state["roots"] = dict(project=str(self.base / "unrelated"))
                atomic_json(state_path, state)
                with self.assertRaisesRegex(ValueError, "roots differ"):
                    delivery_confirmation.capture(self.parent, integrated, record)
                state_path.write_text(original)
        snapshot = delivery_confirmation.capture(self.parent, integrated, record)
        self.assertEqual(snapshot["roots"], dict(project=str(self.repo)))

    def test_server_jenkins_builds_and_reads_recheck_after_personal_waits(self):
        self.confirm()
        with epic_record.changing(self.parent) as record:
            record["phases"] = dict(server="server")
        run = self.runs / "server"
        session = SimpleNamespace(
            environment=dict(run=run, config=dict(phase="server", confirmed_change="parent")),
            active=(run,),
        )
        evidence = self.parent / "plan.json"
        original = evidence.read_text()

        def approve(_request):
            evidence.write_text('{"changed":true}')
            return dict(decision="allow")

        actions = SimpleNamespace(session=session, run=run, folder=run, approve=approve)
        with (
            patch.object(jenkins.client, "request") as request,
            self.assertRaisesRegex(ValueError, "Confirmed"),
        ):
            jenkins.read(actions, dict(operation="status"))
        request.assert_not_called()
        with (
            patch.object(execution_wait, "submit") as submit,
            self.assertRaisesRegex(ValueError, "Confirmed"),
        ):
            jenkins.build(session, dict(operation="build"))
        submit.assert_not_called()
        evidence.write_text(original)
        # Validation stays available before confirmation, as its own delivery phase.
        session.environment["config"]["phase"] = "validation"
        jenkins.authorize(session)

    def test_missing_roots_in_reviewed_or_accepted_records_are_rejected_clearly(self):
        child = self.make_run("child")
        record = dict(tasks={"S1": child.name})
        for member in (self.parent, child):
            with self.subTest(member=member.name):
                path = member / "run.json"
                original = path.read_text()
                state = json.loads(original)
                state.pop("roots")
                atomic_json(path, state)
                with self.assertRaisesRegex(ValueError, "Reviewed delivery roots differ"):
                    delivery_confirmation.capture(self.parent, self.parent, record)
                path.write_text(original)
