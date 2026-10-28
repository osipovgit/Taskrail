"""Executor requests: one parser, same-session feedback, command effects and pushes."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from live_fixture import LiveFixture
from sandbox_fixture import without_sandbox

from taskrail.application.live import execute_task
from taskrail.core import prompt_texts
from taskrail.interactions import (
    actions,
    approval_policy,
    local_policy,
    request_envelope,
    request_routes,
)

ACTION = dict(targets=["web"], script="uptime\n", files={}, reason="Check", timeout_seconds=30)


class RequestEnvelopeTests(unittest.TestCase):
    def test_every_request_type_is_recognized_inside_prose_or_a_fence(self):
        local = dict(schema_version=1, status="LOCAL_REQUEST", cwd="/r", argv=["ls"], reason="x")
        requests = (
            local,
            dict(schema_version=1, status="ACTION_REQUEST", action=ACTION),
            dict(schema_version=1, status="JENKINS_REQUEST", jenkins={}),
        )
        for request in requests:
            fenced = f"Next step:\n```json\n{json.dumps(request)}\n```"
            self.assertEqual(request_envelope.status(fenced), request["status"])
        self.assertIsNone(request_envelope.status('{"schema_version": 2, "outcomes": []}'))
        self.assertIsNone(request_envelope.status("I will now read the file."))

    def test_a_wrong_shape_or_a_wrapped_git_write_is_rejected_with_a_reason(self):
        extra = dict(schema_version=1, status="LOCAL_REQUEST", cwd="/r", argv=["ls"])
        extra.update(reason="x", steps=[])
        with self.assertRaisesRegex(ValueError, "Invalid local request"):
            request_envelope.parsed("LOCAL_REQUEST", json.dumps(extra))
        write = dict(schema_version=1, status="GIT_REQUEST", root="/r", argv=["commit", "-m", "x"])
        write["reason"] = "Commit"
        with self.assertRaisesRegex(ValueError, "entire message"):
            request_envelope.parsed("GIT_REQUEST", "Now:\n" + json.dumps(write))
        self.assertEqual(request_envelope.parsed("GIT_REQUEST", json.dumps(write)), write)


class InspectingStageTests(unittest.TestCase):
    def test_fix_and_in_place_options_are_refused_before_approval(self):
        for argv in (["ruff", "check", "--fix", "."], ["prettier", "--write=true", "x"]):
            with self.assertRaisesRegex(ValueError, "rewrites files"):
                local_policy.read_only(argv)
        with self.assertRaisesRegex(ValueError, "sed -i"):
            local_policy.read_only(["sed", "-i.bak", "s/a/b/", "file"])
        local_policy.read_only(["grep", "-w", "fix", "file"])
        local_policy.read_only(["ruff", "check", "."])


class PushApprovalTests(unittest.TestCase):
    def test_allow_all_and_read_only_rules_never_approve_a_personal_request(self):
        run = Path("/nonexistent-run")
        state = dict(auto_approve=True)
        waited = dict(decision="deny", alternative="")
        with patch.object(approval_policy.approvals, "wait", return_value=waited) as wait:
            answer = approval_policy.decision(run, dict(status="GIT_REQUEST"), state, personal=True)
        self.assertEqual(answer, waited)
        wait.assert_called_once()

    def test_a_push_waits_for_the_operator_outside_the_stage_deadline(self):
        push = dict(schema_version=1, status="GIT_REQUEST", root="/r", reason="Publish")
        push["argv"] = ["push", "origin", "HEAD:refs/heads/fix"]
        with tempfile.TemporaryDirectory() as directory:
            router = actions.Actions.__new__(actions.Actions)
            router.folder, router.run = Path(directory), Path(directory)
            clock = SimpleNamespace(remaining=lambda: 0)
            active = (Path(directory), dict(role="implementer"))
            router.session = SimpleNamespace(state={}, environment={}, clock=clock, active=active)
            outcome = dict(final_text=json.dumps(push))
            declined = dict(decision="alternative", alternative="Push after my review.")
            with (
                patch.object(actions.Actions, "approve", return_value=declined) as approve,
                patch.object(actions.Actions, "git_action") as run,
            ):
                feedback = request_routes.run_git(router, outcome, push)
            self.assertIn("nothing was pushed: Push after my review.", feedback)
            self.assertTrue(approve.call_args.kwargs["personal"])
            run.assert_not_called()
            with (
                patch.object(actions.Actions, "approve", return_value=dict(decision="allow")),
                patch.object(actions.Actions, "git_action", return_value="pushed") as run,
            ):
                self.assertEqual(request_routes.run_git(router, outcome, push), "pushed")
            run.assert_called_once_with(outcome)


class LiveRequestTests(LiveFixture, unittest.TestCase):
    def test_a_malformed_git_request_is_corrected_in_the_same_session(self):
        run, status, state = self.run_mode("bad-git-request")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = [stage for stage in state["stages"] if stage["stage"] == "planner"]
        self.assertEqual(len(planner), 1)
        feedback = (run / planner[0]["directory"] / "tool-result.md").read_text()
        self.assertIn("Your GIT_REQUEST was rejected before anything ran", feedback)
        self.assertIn("Invalid Git request fields", feedback)

    def test_command_effects_are_adopted_journaled_and_reported(self):
        without_sandbox(self)
        self.real_repository()
        (self.root / ".gitignore").write_text(".cache-tool/\n")
        header = {"roots": {"project": str(self.root)}, "auto_approve": True}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        self.configure_mode("local-effects")
        allow = dict(decision="allow", alternative="")
        with patch("taskrail.interactions.approvals.wait", return_value=allow) as wait:
            run, status = execute_task(self.task, self.settings, run_dir=self.base / "result")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        # Allow all actions covers everything else, but the agent's python -c still asked.
        asked = wait.call_args.args[1]
        self.assertEqual((wait.call_count, asked["argv"][1]), (1, "-c"))
        self.assertIn("Allow all actions never approves it", asked["notice"])
        journal = json.loads((run / "local-actions.json").read_text())
        self.assertEqual(journal[0]["effects"], ["project/notes.txt"])
        self.assertEqual(state["command_effects"][0]["files"], ["project/notes.txt"])
        planner = next(stage for stage in state["stages"] if stage["stage"] == "planner")
        feedback = (run / planner["directory"] / "tool-result.md").read_text()
        effects = feedback.split("The command changed files inside the declared roots: ")[1]
        self.assertEqual(effects.split(". They are now", 1)[0], str(self.root / "notes.txt"))
        self.assertIn(prompt_texts.text("feedback.command_effects.read_only"), feedback)
        self.assertNotIn("project/.cache-tool/report.txt", state["changed_files"])
        report = (run / "report.md").read_text()
        self.assertIn("## Changed by approved commands", report)
        self.assertIn(str(self.root / "notes.txt"), report.split("## Changed by approved")[1])


if __name__ == "__main__":
    unittest.main()
