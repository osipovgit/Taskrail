"""What a model reads: field-placed labels, stage-specific instructions within a budget."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from live_fixture import LiveFixture

from taskrail.application import (
    citation_review,
    execution_requests,
    execution_wait,
    instruction_sources,
    prompts,
    recovery,
    task_config,
)
from taskrail.core import prompt_texts, task_spec
from taskrail.infrastructure import agent_profile, artifact_access
from taskrail.web.task_form import build_task

# Bytes of the instructions of one stage, paths shortened; the task and Context excluded.
BUDGETS = {"01-plan": 10500, "02-plan-review": 10500, "03-implement": 9000, "05-review": 9000}
STAGES = dict(zip(("planner", "plan-reviewer", "implementer", "reviewer"), BUDGETS, strict=True))
CAPABILITIES = {
    "hosts": {"test": dict(hostname="server.example.invalid", port=22, username="worker")},
    "jenkins": {
        "ci": dict(
            url="https://ci.example.invalid",
            username="worker",
            jobs={"verify": dict(path="project/verify", parameters=["REF"], approval="root")},
        )
    },
}
STABLE_ID = re.compile(r"R-[0-9a-f]{12}")


class LabelTests(unittest.TestCase):
    def test_a_label_stays_with_its_field_when_the_title_repeats_the_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            goal = "Fix the lint findings in roles/ntp.\n\nKeep variable names stable."
            payload = dict(goal=goal, criteria="ansible-lint roles/ntp passes")
            payload.update(constraints="Do not disable rules.")
            payload["roots"] = [dict(alias="project", path=str(root))]
            text, _ = build_task(payload, Path(directory) / "runs")
        meta = json.loads(text.split("```taskrail-task\n", 1)[1].split("\n```", 1)[0])
        spec = task_spec.resolve(text, dict(meta, verification=["The play runs twice"]))
        shown = task_spec.prompt_text(spec, spec["requirements"])
        self.assertNotIn("## Title", shown)
        self.assertTrue(shown.startswith("## Goal\n[R1]\nFix the lint findings"))
        self.assertIn("\n\n[R2]\nKeep variable names stable.", shown)
        self.assertIn("## Acceptance criteria\n[R3]\nansible-lint", shown)
        self.assertIn("## Constraints\n[R4 constraint]\nDo not disable rules.", shown)
        self.assertIn("## Runtime checks\n[R5 runtime]\nThe play runs twice", shown)


class FrozenTextTests(unittest.TestCase):
    def test_declined_unknown_and_repair_feedback_keep_a_continued_runs_catalog(self):
        self.addCleanup(prompt_texts.ACTIVE.adopt, prompt_texts.release())
        frozen = prompt_texts.release()
        frozen.update(
            {
                "feedback.remote_declined": "Frozen denial: skip the action",
                "feedback.remote_unknown": "Frozen uncertainty: inspect before another action",
                "repair.header": "Frozen repair boundary: only reformat observed facts",
            }
        )
        updated = dict(frozen)
        for key in ("feedback.remote_declined", "feedback.remote_unknown", "repair.header"):
            updated[key] = "New release instructions"
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "00-input").mkdir()
            with mock.patch.object(prompt_texts, "release", return_value=frozen):
                instruction_sources.freeze_contract(run, prompts.POLICY, {})
            contract = (run / "00-input/contract.json").read_bytes()
            with (
                mock.patch.object(prompt_texts, "release", return_value=updated),
                mock.patch.object(
                    execution_wait.client, "request", side_effect=AssertionError("No replay")
                ),
            ):
                instruction_sources.adopt_texts(run)
                (run / execution_wait.LEDGER).write_text(json.dumps([dict(status="REJECTED")]))
                self.assertEqual(
                    execution_wait.resume(run, dict(attempts=[])),
                    frozen["feedback.remote_declined"],
                )
                (run / execution_wait.LEDGER).write_text(json.dumps([dict(status="UNKNOWN")]))
                with self.assertRaisesRegex(ValueError, "Frozen uncertainty"):
                    execution_wait.resume(run, dict(attempts=[]))
                repaired = prompts.repair("{}", "Missing outcome", "reviewer", 1, [])
                self.assertTrue(repaired.startswith(frozen["repair.header"]))
                self.assertNotIn("New release instructions", repaired)
            self.assertEqual((run / "00-input/contract.json").read_bytes(), contract)

    def test_runtime_artifacts_and_feedback_use_the_frozen_catalog(self):
        self.addCleanup(prompt_texts.ACTIVE.adopt, prompt_texts.release())
        entries = prompt_texts.release()
        entries.update(
            {
                "recovery.header": ["Frozen recovery instructions"],
                "recovery.index": ["", "Frozen recovery index"],
                "manifest.search": "Frozen manifest instructions",
                "citation.source_view": "Frozen view guidance: $path ($lines)",
            }
        )
        prompt_texts.ACTIVE.adopt(entries)
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            evidence = dict(source="events.jsonl", records=[], omitted=0)
            recovery.write_evidence(run / "recovery.md", evidence)
            text = (run / "recovery.md").read_text()
            self.assertIn("Frozen recovery instructions", text)
            self.assertIn("Frozen recovery index", text)
            manifest = artifact_access.manifest(run, run, {})
            self.assertEqual(manifest["search"], "Frozen manifest instructions")
            view = dict(path=str(run / "view.json"), lines=8)
            with mock.patch(
                "taskrail.application.citation_review.source_views.prepare", return_value=view
            ):
                feedback = citation_review.guidance(
                    dict(path="/source.json"), dict(run=run, roots={}), "clipped", {}
                )
            self.assertEqual(feedback, f"Frozen view guidance: {view['path']} (8)")

    def test_a_continued_run_keeps_the_texts_it_started_with(self):
        self.addCleanup(prompt_texts.ACTIVE.adopt, prompt_texts.release())
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "00-input").mkdir()
            instruction_sources.freeze_contract(run, prompts.POLICY, {})
            contract = run / "00-input/contract.json"
            saved = json.loads(contract.read_text())
            saved["texts"]["stage.planner"] = "Stage: planning (frozen)."
            contract.write_text(json.dumps(saved))
            instruction_sources.freeze_contract(run, prompts.POLICY, {})
            self.assertEqual(prompt_texts.text("stage.planner"), "Stage: planning (frozen).")
            del saved["texts"]
            contract.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, "differs from this release"):
                instruction_sources.freeze_contract(run, prompts.POLICY, {})

    def test_missing_catalog_keys_require_restart_on_both_resume_paths(self):
        self.addCleanup(prompt_texts.ACTIVE.adopt, prompt_texts.release())
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "00-input").mkdir()
            saved = instruction_sources.freeze_contract(run, prompts.POLICY, {})
            del saved["texts"]["citation.source_view"]
            (run / "00-input/contract.json").write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, "restart"):
                instruction_sources.freeze_contract(run, prompts.POLICY, {})
            with self.assertRaisesRegex(ValueError, "restart"):
                instruction_sources.adopt_texts(run)

    def test_new_tasks_do_not_inherit_another_runs_frozen_texts(self):
        self.addCleanup(prompt_texts.ACTIVE.adopt, prompt_texts.release())
        entries = prompt_texts.release()
        entries["task.default_criteria"] = "Old task default"
        entries["task.workflow_rules"] = "Old task rules"
        prompt_texts.ACTIVE.adopt(entries)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            payload = dict(
                goal="Write installation documentation", roots=[dict(alias="p", path=str(root))]
            )
            text, _ = build_task(payload, Path(directory) / "runs")
        self.assertNotIn("Old task", text)
        self.assertIn(prompt_texts.current("task.default_criteria"), text)


class CapabilityTests(unittest.TestCase):
    def test_format_repairs_are_bounded_and_never_offer_executor_routes(self):
        requirements = [dict(id="R-0123456789ab", kind="task", text="Fix the requested behavior")]
        for stage in ("implementer", "plan-reviewer", "reviewer"):
            with (
                self.subTest(stage=stage),
                mock.patch.object(
                    execution_requests,
                    "available",
                    side_effect=AssertionError("Repair cannot execute"),
                ),
            ):
                request = prompts.repair("{}", "Missing outcome", stage, 1, requirements)
            encoded = request.split("\nSchema:\n", 1)[1].split("\nAssigned requirements:", 1)[0]
            contract = json.loads(encoded)
            self.assertEqual(contract["properties"]["schema_version"]["enum"], [2])
            self.assertNotIn("status", contract["properties"])
            self.assertNotIn("_REQUEST", encoded)
            profile = prompt_texts.text("profile.converter") + prompt_texts.text(
                "profile.runtime_rules"
            )
            self.assertLess(len((request + profile).encode()), BUDGETS[STAGES[stage]])

    def test_absent_and_unreachable_executors_do_not_advertise_remote_schemas(self):
        with mock.patch("taskrail.application.execution_requests.Path.exists", return_value=False):
            self.assertEqual(
                execution_requests.available(), {"unavailable": "routes.ssh.unavailable"}
            )
        with (
            mock.patch("taskrail.application.execution_requests.Path.exists", return_value=True),
            mock.patch(
                "taskrail.application.execution_requests.client.request", side_effect=OSError
            ),
        ):
            self.assertEqual(
                execution_requests.available(), {"unavailable": "routes.ssh.unreachable"}
            )


class RequestBudgetTests(LiveFixture, unittest.TestCase):
    def test_capabilities_modes_and_language_modules_keep_the_same_stage_budgets(self):
        run, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        config = task_config.configuration(self.task, self.settings)
        plan = dict(files_read=["project/hello.py", "project/check.sh", "project/ui.js"])
        plan["proposed_change_files"] = []
        catalogs = (
            {"unavailable": "routes.ssh.unavailable"},
            {"unavailable": "routes.ssh.unreachable"},
            {},
            {"hosts": CAPABILITIES["hosts"]},
            {"jenkins": CAPABILITIES["jenkins"]},
            CAPABILITIES,
        )
        modes = (
            ({}, tuple(STAGES)),
            ({"decompose": True}, ("planner", "plan-reviewer")),
            ({"read_only": True}, ("planner", "reviewer")),
            ({"read_only": True, "design": True}, ("planner", "reviewer")),
            (
                {"phase": "task", "assigned_contract": {"task_id": "T1"}},
                ("implementer", "reviewer"),
            ),
            ({"phase": "integration"}, ("reviewer",)),
            ({"phase": "server", "confirmed_change": "change"}, ("planner", "reviewer")),
        )
        for catalog in catalogs:
            for overrides, stages in modes:
                for stage in stages:
                    with (
                        self.subTest(catalog=catalog, mode=overrides, stage=stage),
                        mock.patch(
                            "taskrail.application.execution_requests.available",
                            return_value=catalog,
                        ) as available,
                    ):
                        request = prompts.make_request(
                            dict(config, **overrides), (stage, plan, [], None), state, run
                        )
                        available.assert_called_once_with()
                        self.check_budget(request, stage)
                        ssh = bool(catalog.get("hosts")) and stage != "implementer"
                        self.assertEqual('"status":{"const":"ACTION_REQUEST"}' in request, ssh)
                        self.assertEqual(
                            '"status":{"const":"JENKINS_REQUEST"}' in request,
                            bool(catalog.get("jenkins")),
                        )

    def check_budget(self, request, stage):
        assert_request_budget(self, request, stage, self.base)

    def test_each_stage_reads_only_its_own_instructions_within_budget(self):
        run, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        requests = {}
        for stage, budget in BUDGETS.items():
            request = (run / stage / "request.md").read_text()
            short = request.replace(str(self.base), "/B")
            instructions = short.split("# Orchestrator instructions\n", 1)[1]
            instructions = instructions.split("\nContext:\n", 1)[0]
            self.assertLess(len(instructions.encode()), budget, stage)
            self.assertIsNone(STABLE_ID.search(request), stage)
            self.assertNotIn("{'", request)
            requests[stage] = request
        self.assertIn("Your only writable file is the plan file", requests["01-plan"])
        self.assertNotIn("Your only writable file", requests["03-implement"])
        self.assertIn("Edit only the allowed files", requests["03-implement"])
        self.assertNotIn("Edit only the allowed files", requests["05-review"])
        self.assertIn("A push waits for the operator's approval", requests["03-implement"])
        self.assertNotIn("push", requests["05-review"].split("Local commands:")[0])
        self.assertNotIn('"findings"', requests["03-implement"])
        self.assertEqual(requests["01-plan"].count("as your entire message"), 3)
        progress = run / "progress.md"
        self.assertIn(
            f"PROGRESS FILE: {progress}", requests["03-implement"].replace("/B", str(self.base))
        )
        self.assertNotIn("PROGRESS FILE", requests["05-review"])
        self.assertIn("## Remaining", progress.read_text())
        profile = json.loads((run / "03-implement/agent.md").read_text().split("---")[1])
        self.assertEqual(profile["permission"]["edit"][str(progress)], "allow")


def assert_request_budget(test, request, stage, base):
    """Bound instruction bytes and the actual role body plus runtime rule independently."""
    shortened = request.replace(str(base), "/B")
    instructions = shortened.split("# Orchestrator instructions\n", 1)[1].split("\nContext:\n", 1)[
        0
    ]
    budget = BUDGETS[STAGES[stage]]
    test.assertLess(len(instructions.encode()), budget, stage)
    role = "reviewer" if stage == "plan-reviewer" else stage
    source = Path(__file__).resolve().parents[1] / "taskrail/agents" / f"{role}.md"
    profile = agent_profile.body(source) + prompt_texts.text("profile.runtime_rules")
    test.assertLess(len((shortened + profile).encode()), budget + 2500, stage)


if __name__ == "__main__":
    unittest.main()
