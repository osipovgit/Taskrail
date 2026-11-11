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
    feedback_files,
    instruction_sources,
    prompts,
    recovery,
    task_config,
)
from taskrail.core import prompt_texts, task_spec, task_understanding
from taskrail.infrastructure import agent_profile, artifact_access
from taskrail.web.task_form import build_task

# Bytes of the instructions of one stage, paths shortened; the task and Context excluded.
BUDGETS = {
    "01-understand": 5000,
    "02-plan": 10500,
    "03-plan-review": 10500,
    "04-implement": 9000,
    "06-review": 9000,
}
STAGES = dict(
    zip(
        ("understanding", "planner", "plan-reviewer", "implementer", "reviewer"),
        BUDGETS,
        strict=True,
    )
)
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


class FeedbackFileTests(unittest.TestCase):
    def test_all_findings_are_pageable_and_losslessly_delivered_to_both_roles(self):
        text = 'λ"\0\n' * 2000
        rows = [dict(id=f"F{n}", evidence=text if n == 20 else str(n)) for n in range(1100)]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            feedback = feedback_files.findings(folder, dict(findings=rows))
            payload = Path(feedback["findings_file"]).read_text()
            decoded = json.loads(payload)["findings"]
            self.assertEqual(feedback["lines"], len(payload.splitlines()))
            self.assertLess(max(len(line.encode()) for line in payload.splitlines()), 1000)
            self.assertEqual(len(decoded), len(rows))
            self.assertEqual("".join(decoded[20]["evidence"]["text_chunks"]), text)
            self.assertEqual(decoded[-1], rows[-1])


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
        payload = dict(
            summary="Fixture obligations",
            requirements=[
                dict(text=text, kind=kind, sources=[dict(field=field, quote=text)])
                for field, text, kind in (
                    ("goal", "Fix the lint findings in roles/ntp.", "task"),
                    ("goal", "Keep variable names stable.", "task"),
                    ("criteria", "ansible-lint roles/ntp passes", "task"),
                    ("constraints", "Do not disable rules.", "constraint"),
                )
            ],
        )
        entries = task_understanding.resolve(payload, spec)["requirements"]
        shown = task_spec.prompt_text(spec, entries)
        self.assertNotIn("## Title", shown)
        self.assertTrue(shown.startswith("## Goal\n[R1]\nFix the lint findings"))
        self.assertIn("\n\n[R2]\nKeep variable names stable.", shown)
        self.assertIn("## Acceptance criteria\n[R3]\nansible-lint", shown)
        self.assertIn("## Constraints\n[R4 constraint]\nDo not disable rules.", shown)
        self.assertIn("## Runtime checks\n[R5 runtime]\nThe play runs twice", shown)


class FrozenTextTests(unittest.TestCase):
    def test_declined_and_unknown_feedback_does_not_replay_a_remote_action(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                execution_wait.client, "request", side_effect=AssertionError("No replay")
            ),
        ):
            run = Path(directory)
            ledger = run / execution_wait.LEDGER
            ledger.write_text(json.dumps([dict(status="REJECTED")]))
            self.assertEqual(
                execution_wait.resume(run, dict(attempts=[])),
                prompt_texts.text("feedback.remote_declined"),
            )
            ledger.write_text(json.dumps([dict(status="UNKNOWN")]))
            with self.assertRaisesRegex(
                ValueError, re.escape(prompt_texts.text("feedback.remote_unknown"))
            ):
                execution_wait.resume(run, dict(attempts=[]))

    def test_runtime_artifacts_and_feedback_render_catalog_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            evidence = dict(source="events.jsonl", records=[], omitted=0)
            recovery.write_evidence(run / "recovery.md", evidence)
            text = (run / "recovery.md").read_text()
            self.assertIn(prompt_texts.text("recovery.header"), text)
            self.assertIn(prompt_texts.text("recovery.index"), text)
            manifest = artifact_access.manifest(run, run, {})
            self.assertEqual(manifest["search"], prompt_texts.text("manifest.search"))
            view = dict(path=str(run / "view.json"), lines=8)
            with mock.patch.object(citation_review.source_views, "prepare", return_value=view):
                feedback = citation_review.guidance(
                    dict(path="/source.json"), dict(run=run, roots={}), "clipped", {}
                )
            self.assertEqual(
                feedback, prompt_texts.text("citation.source_view", error="clipped", **view)
            )

    def test_new_stage_rejects_changed_contract_even_with_its_fingerprint(self):
        from taskrail.core.files import atomic_json, digest

        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            state = {}
            instruction_sources.capture(run, state, instruction_sources.BUNDLED_AGENTS)
            path = run / instruction_sources.CONTRACT
            original = path.read_bytes()
            for section in ("policy", "texts", "schemas"):
                with self.subTest(section=section):
                    document = json.loads(original)
                    del document[section]
                    atomic_json(path, document)
                    state[instruction_sources.SIGNATURE] = digest(path.read_bytes())
                    with self.assertRaisesRegex(ValueError, "instruction contract"):
                        prompts.make_request({}, ("planner", None, [], None), state, run)
            path.unlink()
            state[instruction_sources.SIGNATURE] = digest(original)
            with self.assertRaisesRegex(ValueError, "instruction contract"):
                prompts.make_request({}, ("planner", None, [], None), state, run)
            self.assertFalse(path.exists())


class CapabilityTests(unittest.TestCase):
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
        with self.subTest(requests="saved stage instructions"):
            self.check_saved_requests(run)
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
            (
                {
                    "worktrees": {
                        "project": dict(
                            source=str(self.base / "original checkout"), worktree=str(self.root)
                        )
                    }
                },
                tuple(STAGES),
            ),
            ({"decompose": True}, ("planner", "plan-reviewer")),
            ({"read_only": True}, ("planner", "reviewer")),
            ({"read_only": True, "design": True}, ("planner", "reviewer")),
            (
                {"phase": "task", "assigned_contract": {"task_id": "T1"}},
                ("implementer", "reviewer"),
            ),
            ({"phase": "integration"}, ("reviewer",)),
            ({"phase": "correction"}, tuple(STAGES)),
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
                        if stage == "understanding":
                            available.assert_not_called()
                        else:
                            available.assert_called_once_with()
                        self.check_budget(request, stage)
                        ssh = bool(catalog.get("hosts")) and stage not in {
                            "understanding",
                            "implementer",
                        }
                        self.assertEqual("Example ACTION_REQUEST:" in request, ssh)
                        self.assertEqual(
                            "Example JENKINS_REQUEST:" in request,
                            bool(catalog.get("jenkins")) and stage != "understanding",
                        )

    def check_budget(self, request, stage):
        assert_request_budget(self, request, stage, self.base)

    def check_saved_requests(self, run):
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
        self.assertNotIn("Use LOCAL_REQUEST", requests["01-understand"])
        self.assertIn("even with an empty check_catalog", requests["03-plan-review"])
        self.assertIn("Your only writable file is the plan file", requests["02-plan"])
        self.assertIn("The planner was given these rules", requests["03-plan-review"])
        self.assertNotIn("The planner was given these rules", requests["02-plan"])
        for stage in ("02-plan", "03-plan-review"):
            self.assertIn("project-wide check to one task", requests[stage])
            self.assertIn("compare individual diagnostics", requests[stage])
        self.assertNotIn("Cite current lines", requests["04-implement"])
        self.assertIn("Your task from the approved plan:", requests["04-implement"])
        self.assertIn("Done when:\n- ", requests["04-implement"])
        self.assertNotIn("Your task from the approved plan", requests["06-review"])
        self.assertIn("Cite current lines", requests["06-review"])
        self.assertNotIn("Your only writable file", requests["04-implement"])
        self.assertIn("Context.planned_files lists expected targets", requests["04-implement"])
        self.assertNotIn("Context.planned_files lists expected targets", requests["06-review"])
        self.assertIn("Push needs personal approval", requests["04-implement"])
        self.assertNotIn("push", requests["06-review"].split("Local commands:")[0])
        self.assertNotIn('"findings"', requests["04-implement"])
        self.assertEqual(requests["02-plan"].count("as your entire message"), 1)
        progress = run / "progress.md"
        self.assertIn(
            f"PROGRESS FILE: {progress}", requests["04-implement"].replace("/B", str(self.base))
        )
        self.assertNotIn("PROGRESS FILE", requests["06-review"])
        self.assertIn("## Remaining", progress.read_text())
        profile = json.loads((run / "04-implement/agent.md").read_text().split("---")[1])
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
