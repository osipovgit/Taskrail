"""On-request acceptance of complete realistic tasks with independently checked outputs."""

import json
import unittest

from corpus import CORPUS
from oracles import docker, pricing, verify
from workflow_fixture import ScenarioFixture

from taskrail.core.files import atomic_json
from taskrail.web import epic_launch, epic_tasks, integration_review


class ScenarioWorkflows(ScenarioFixture, unittest.TestCase):
    def test_single_task_deliverables_keep_scope_and_independent_review(self):
        for case in CORPUS["tasks"]:
            if case["mode"] == "split":
                continue
            with self.subTest(task=case["id"]):
                self.prepare(case)
                run, status, state = self.execute()
                self.assertEqual(status, case["expected_status"], state.get("summary"))
                frozen = {field["name"]: field["text"] for field in state["task_spec"]["fields"]}
                for name in ("goal", "criteria", "constraints"):
                    self.assertEqual(frozen[name], case[name])
                self.assert_preserved(case["changes"])
                expected = ["planner", "plan-reviewer"]
                if case["changes"]:
                    expected += ["implementer", "reviewer"]
                self.assertEqual([stage["stage"] for stage in state["attempts"]], expected)
                verify(self, case, self.roots, self.base)
                if case["mode"] == "design":
                    design = (run / "design.md").read_text()
                    for heading in (
                        "Context",
                        "Options",
                        "Trade-offs",
                        "Recommendation",
                        "Risks",
                        "Implementation outline",
                        "Open questions",
                    ):
                        self.assertIn("### " + heading, design)
                    for fact in (
                        "30 seconds",
                        "existing UI field",
                        "default values",
                        "compatibility",
                    ):
                        self.assertIn(fact, design)
                if case["mode"] == "answer":
                    configured = json.loads((self.roots["service"] / "config.json").read_text())
                    self.assertIn(f"retry count is {configured['retries']}", state["answer"])
                    self.assertIn(f"{configured['timeout_seconds']} seconds", state["answer"])
                    self.assertIn(f"{self.roots['service'] / 'config.json'}:1-1", state["answer"])
                if case["id"] == "ANSIBLE-LINT":
                    reviewed = json.loads((run / state["results"]["review"]).read_text())
                    runtime = {
                        entry["id"] for entry in state["requirements"] if entry["kind"] == "runtime"
                    }
                    observed = {entry["id"]: entry["outcome"] for entry in reviewed["coverage"]}
                    self.assertTrue(runtime)
                    self.assertEqual({observed[identifier] for identifier in runtime}, {"deferred"})
                    self.assertFalse(state.get("execution_jobs"))

    def test_multi_root_children_then_combined_review_preserve_global_constraints(self):
        case = next(case for case in CORPUS["tasks"] if case["mode"] == "split")
        self.prepare(case)
        parent, status, state = self.execute("parent")
        self.assertEqual(status, "TASKS_READY", state.get("summary"))
        self.assert_preserved({})
        linked = {}
        for number in (1, 2):
            entries = epic_tasks.tasks(parent, state)
            entry = entries[number - 1]
            payload = epic_launch.payload(parent, state, entries, entry)
            self.assertIn("Preserve retries", payload["constraints"])
            child, status, child_state = self.execute(f"child-{number}", payload)
            self.assertEqual(status, "READY_FOR_REVIEW", child_state.get("summary"))
            self.assertEqual(
                [stage["stage"] for stage in child_state["attempts"]], ["implementer", "reviewer"]
            )
            linked[entry["id"]] = child.name
            atomic_json(parent / "epic.json", dict(tasks=linked))
        atomic_json(
            parent / "epic.json", dict(tasks=linked, phases=dict(integration="integration"))
        )
        review, status, reviewed = self.execute(
            "integration", integration_review.payload(parent, state)
        )
        self.assertEqual(status, "NO_CHANGES_REQUIRED", reviewed.get("summary"))
        self.assertEqual([stage["stage"] for stage in reviewed["attempts"]], ["reviewer"])
        self.assertIn("timeout_seconds", (review / "changes.diff").read_text())
        self.assertIn("timeoutSeconds", (review / "changes.diff").read_text())
        self.assertEqual(
            json.loads((self.roots["service"] / "config.json").read_text())["timeout_seconds"], 45
        )
        self.assertIn("timeoutSeconds: 45", (self.roots["ui"] / "settings.js").read_text())
        self.assert_preserved(case["changes"])

    def test_pricing_writer_cannot_hide_damage_to_unrelated_user_notes(self):
        case = next(case for case in CORPUS["tasks"] if case["id"] == "PERCENT-DISCOUNT")
        self.prepare(dict(case, fault="scope"))
        _, status, state = self.execute()
        self.assertEqual(status, "BLOCKED", state.get("summary"))
        self.assertIn("Scope violation", state["summary"])
        self.assertNotIn("reviewer", [stage["stage"] for stage in state["attempts"]])

    def test_independent_oracles_reject_the_unfixed_seed_projects(self):
        for name, oracle in (("PERCENT-DISCOUNT", pricing), ("IMAGE-CACHE", docker)):
            with self.subTest(task=name):
                case = next(case for case in CORPUS["tasks"] if case["id"] == name)
                self.prepare(case)
                probe = unittest.TestCase()
                with self.assertRaises(AssertionError):
                    if name == "IMAGE-CACHE":
                        oracle(probe, self.roots["service"], self.base)
                    else:
                        oracle(probe, self.roots["service"])
