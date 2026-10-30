"""Personal local-action grants survive Continue and reach only linked child workers."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from live_fixture import LiveFixture

from taskrail.application.live import execute_task
from taskrail.core import approval_family, approval_marks
from taskrail.core.files import atomic_json
from taskrail.infrastructure import sandbox
from taskrail.interactions import approval_policy, approvals
from taskrail.web import history, split_approvals


class ApprovalInheritanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.parent = self.worker("parent")
        self.child = self.worker("child", "S-1")
        self.request = dict(status="LOCAL_REQUEST", argv=["ansible-lint", "--version"], cwd="/p")
        self.epic = dict(tasks={"S-1": "child"}, attempts={"S-1": ["child"]})
        atomic_json(self.parent / "epic.json", self.epic)

    def worker(self, name, slot=None):
        run = self.base / name
        (run / "00-input").mkdir(parents=True)
        metadata = dict(roots={"p": "/p"})
        if slot:
            metadata.update(phase="task", assigned_contract=dict(parent_run="parent", task_id=slot))
        (run / "00-input/task.md").write_text(
            f"```taskrail-task\n{json.dumps(metadata)}\n```\nLint"
        )
        atomic_json(run / "run.json", dict(roots={"p": "/p"}, auto_approve=False))
        return run

    def grant(self, run):
        atomic_json(run / approvals.PENDING, dict(ticket="ticket", request=self.request))
        split_approvals.decide(
            run,
            dict(id=run.name, ticket="ticket", decision="allow", alternative="", allow_all=True),
        )

    def assert_automatic(self, run, state=None):
        with patch.object(approvals, "wait") as asked:
            answer = approval_policy.decision(run, self.request, state or {})
        asked.assert_not_called()
        self.assertEqual(answer["rule"], approval_policy.ALLOW_ALL)

    def test_card_grant_survives_continue_even_if_the_task_header_never_granted_it(self):
        self.grant(self.child)
        self.assertTrue(approval_policy.at_start(self.child, {}, dict(auto_approve=True)))
        self.assertTrue(approval_policy.at_start(self.child, {}, {}))
        self.assert_automatic(self.child)
        self.assertTrue(history.task_draft(self.child)["auto_approve"])

    def test_parent_card_grant_reaches_existing_new_and_restarted_children(self):
        self.grant(self.parent)
        self.assert_automatic(self.child, dict(auto_approve=False))
        for name in ("second", "retry"):
            run = self.worker(name, "S-1")
            record = json.loads((self.parent / "epic.json").read_text())
            record["attempts"]["S-1"].append(name)
            record["tasks"]["S-1"] = name
            atomic_json(self.parent / "epic.json", record)
            self.assert_automatic(run)

    def test_pre_upgrade_family_grant_refreshes_a_running_child(self):
        atomic_json(self.parent / "epic.json", dict(self.epic, auto_approve=True))
        self.assert_automatic(self.child)

    def test_linked_correction_phase_inherits_grants_and_ancestor_revocation(self):
        run = self.worker("correction")
        metadata = dict(phase="correction", check_parent="parent")
        (run / "00-input/task.md").write_text(f"```taskrail-task\n{json.dumps(metadata)}\n```\nFix")
        self.grant(self.parent)
        record = json.loads((self.parent / "epic.json").read_text())
        record["phases"] = dict(correction=run.name)
        atomic_json(self.parent / "epic.json", record)
        self.assert_automatic(run)
        approval_marks.revoke(self.parent)
        self.assertFalse(approval_policy.enabled(run, dict(auto_approve=True)))

    def test_ancestor_revocation_overrides_copied_child_flags_before_the_next_linter(self):
        self.grant(self.parent)
        state = dict(auto_approve=True)
        approval_marks.revoke(self.parent)
        with patch.object(approvals, "wait", return_value=dict(decision="deny")) as asked:
            approval_policy.decision(self.child, self.request, state)
        asked.assert_called_once()
        self.assertFalse(state["auto_approve"])
        self.assertFalse(approval_policy.at_start(self.child, dict(auto_approve=True)))
        self.assertFalse(history.task_draft(self.child)["auto_approve"])

    def test_a_new_family_grant_does_not_clear_an_old_worker_revocation(self):
        approval_marks.revoke(self.child)
        self.grant(self.parent)
        self.assertFalse(approval_policy.enabled(self.child, dict(auto_approve=True)))

    def test_unlinked_task_metadata_and_wrong_slot_cannot_inherit_a_grant(self):
        self.grant(self.parent)
        for name, slot in (("unlinked", "S-1"), ("wrong-slot", "S-2")):
            run = self.worker(name, slot)
            with patch.object(approvals, "wait", return_value=dict(decision="deny")) as asked:
                approval_policy.decision(run, self.request, {})
            asked.assert_called_once()
            self.assertIsNone(approval_family.parent(run))

    def test_corrupt_or_removed_parent_links_cannot_restore_a_revoked_inherited_grant(self):
        self.grant(self.parent)
        approval_marks.revoke(self.parent)
        for record in ("{broken", "{}", '{"tasks":{"S-2":"child"}}'):
            with self.subTest(record=record):
                (self.parent / "epic.json").write_text(record)
                self.assertFalse(approval_policy.enabled(self.child, dict(auto_approve=True)))
                self.assertFalse(approval_policy.at_start(self.child, dict(auto_approve=True)))
        (self.parent / "epic.json").unlink()
        self.assertFalse(approval_policy.enabled(self.child, dict(auto_approve=True)))

    def test_missing_or_corrupt_child_task_cannot_restore_copied_authority(self):
        self.grant(self.parent)
        task = self.child / "00-input/task.md"
        task.write_text("```taskrail-task\n{broken\n```\n")
        self.assertFalse(approval_policy.enabled(self.child, dict(auto_approve=True)))
        task.write_text("No parent mentioned.\n")
        self.assertFalse(approval_policy.enabled(self.child, dict(auto_approve=True, phase="task")))
        task.unlink()
        self.assertFalse(approval_policy.enabled(self.child, dict(auto_approve=True)))

    def test_without_a_personal_grant_the_host_linter_still_waits(self):
        with patch.object(approvals, "wait", return_value=dict(decision="deny")) as asked:
            approval_policy.decision(self.child, self.request, {})
        asked.assert_called_once()


class ApprovalContinueTests(LiveFixture, unittest.TestCase):
    def test_continued_worker_keeps_its_saved_grant_for_real_host_verification(self):
        self.real_repository()
        check = dict(cwd=str(self.root), argv=[sys.executable, "-c", "print('lint passed')"])
        with patch.object(sandbox, "mode", return_value=None):
            run, status, state = self.run_mode(
                "writer-timeout",
                verify_commands=[check],
                worktree_base=str(self.base / "worktrees"),
            )
        self.assertEqual(status, "TIMEOUT")
        state["auto_approve"] = True
        atomic_json(run / "run.json", state)
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        settings["timeout_seconds"] = 5
        self.settings.write_text(json.dumps(settings))
        with (
            patch.object(sandbox, "mode", return_value=None),
            patch.object(approvals, "wait", side_effect=AssertionError("Unexpected linter prompt")),
        ):
            _, status = execute_task(
                run / "00-input/task.md", self.settings, run_dir=run, resume=True
            )
        self.assertEqual(status, "READY_FOR_REVIEW", (run / "report.md").read_text())
        actions = json.loads((run / "local-actions.json").read_text())
        self.assertEqual(actions[-1]["approval"]["rule"], approval_policy.ALLOW_ALL)
        self.assertEqual(actions[-1]["status"], "SUCCEEDED")
