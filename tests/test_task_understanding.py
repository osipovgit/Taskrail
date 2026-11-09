"""Narrative input, exact provenance and repair of model-derived obligations."""

import copy
import json
import unittest

from live_fixture import LiveFixture

from taskrail.core import requirements, task_lineage, task_spec, task_understanding

NARRATIVE = (
    "Сервис написан на Java, раньше он использовал Redis. "
    "Сначала проверь исходные правки и сделай отдельный коммит. "
    "Затем исправь повторную отправку сообщений. Публичный API менять нельзя."
)
QUOTES = (
    "Сначала проверь исходные правки и сделай отдельный коммит.",
    "Затем исправь повторную отправку сообщений.",
    "Публичный API менять нельзя.",
)


def interpreted():
    texts = (
        "First review the existing edits and commit them separately.",
        "Then fix duplicate message delivery.",
        "Preserve the public API.",
    )
    entries = [
        dict(
            text=text,
            kind="constraint" if number == 2 else "task",
            sources=[dict(field="goal", quote=quote)],
        )
        for number, (text, quote) in enumerate(zip(texts, QUOTES, strict=True))
    ]
    return dict(summary="Repair delivery after reviewing pending edits", requirements=entries)


class TaskUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.spec = task_spec.from_fields(dict(goal=NARRATIVE, current_behavior="No new broker."))
        self.spec["requirements"] = [
            requirements.requirement("Check the deployed service", "runtime")
        ]

    def resolve(self, payload=None):
        return task_understanding.resolve(payload or interpreted(), self.spec)["requirements"]

    def test_one_narrative_keeps_background_ordering_and_global_constraints_distinct(self):
        original = copy.deepcopy(self.spec)
        entries = self.resolve()
        self.assertEqual(len(entries), 4)
        self.assertIn("First review", entries[0]["text"])
        self.assertIn("Then fix", entries[1]["text"])
        self.assertEqual(entries[2]["kind"], "constraint")
        self.assertEqual(entries[3], self.spec["requirements"][0])
        for entry, quote in zip(entries, QUOTES, strict=False):
            source = entry["sources"][0]
            self.assertEqual(NARRATIVE[source["start"] : source["end"]], quote)
        self.assertEqual(self.spec, original)
        shown = task_spec.prompt_text(self.spec, entries)
        self.assertIn(NARRATIVE, shown)
        self.assertIn("No new broker.", shown)
        self.assertNotIn("Redis", " ".join(entry["text"] for entry in entries))

    def test_title_requirements_keep_their_labels_even_when_repeated_in_the_goal(self):
        for goal in ("Read before editing.", "Review pending edits. Then fix the bug."):
            spec = task_spec.from_fields(dict(title="Review pending edits.", goal=goal))
            spec["requirements"] = []
            payload = dict(
                summary="Interpret title",
                requirements=[
                    dict(
                        text="Review pending edits.",
                        kind="task",
                        sources=[dict(field="title", quote="Review pending edits.")],
                    )
                ],
            )
            entries = task_understanding.resolve(payload, spec)["requirements"]
            shown = task_spec.prompt_text(spec, entries)
            self.assertIn("## Title\n[R1]\nReview pending edits.", shown)
            self.assertIn(goal, shown)

    def test_explicit_constraints_cannot_be_downgraded_to_optional_task_ownership(self):
        self.spec["fields"][-1]["text"] = "Preserve the public API."
        payload = interpreted()
        payload["requirements"][2] = dict(
            text="Preserve the public API.",
            kind="task",
            sources=[dict(field="constraints", quote="Preserve the public API.")],
        )
        with self.assertRaisesRegex(ValueError, "global constraints"):
            self.resolve(payload)

    def test_requests_in_current_behavior_are_valid_input_sources(self):
        payload = interpreted()
        payload["requirements"].append(
            dict(
                text="Do not add another broker.",
                kind="constraint",
                sources=[dict(field="current_behavior", quote="No new broker.")],
            )
        )
        self.assertEqual(self.resolve(payload)[3]["sources"][0]["field"], "current_behavior")

    def test_invented_missing_and_ambiguous_sources_return_validation_errors(self):
        for source in (
            dict(field="goal", quote="invented"),
            dict(field="history", quote=QUOTES[0]),
            dict(field="goal", quote=QUOTES[0], occurrence=2),
            dict(field="goal", quote=QUOTES[0], occurrence=True),
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                payload = interpreted()
                payload["requirements"][0]["sources"] = [source]
                self.resolve(payload)
        self.spec["fields"][1]["text"] = QUOTES[0] + QUOTES[0]
        with self.assertRaisesRegex(ValueError, "occurrence"):
            self.resolve()
        source = dict(field="goal", quote=QUOTES[0], occurrence=2)
        bound = task_understanding.reference(source, dict(goal=QUOTES[0] + QUOTES[0]))
        self.assertEqual(bound["start"], len(QUOTES[0]))

    def test_unchanged_requirements_keep_ids_across_reordering_and_partial_correction(self):
        before = self.resolve()
        payload = interpreted()
        payload["requirements"][1]["text"] = "Then make delivery idempotent."
        payload["requirements"].reverse()
        after = {entry["text"]: entry for entry in self.resolve(payload)}
        for entry in (before[0], before[2], before[3]):
            self.assertEqual(after[entry["text"]]["id"], entry["id"])
        self.assertNotIn(before[1]["id"], {entry["id"] for entry in after.values()})

    def test_narrative_constraints_are_inherited_by_every_child(self):
        entries = self.resolve()
        child = task_lineage.for_step(entries, dict(criteria=[entries[0]["id"]], done_when=[]))
        self.assertEqual(
            [entry["parent_id"] for entry in child], [entries[0]["id"], entries[2]["id"]]
        )
        self.assertEqual(task_lineage.checked_assignments(child), child)

    def test_repeated_interpretation_failure_keeps_the_prior_plan_for_checkpoint_resume(self):
        from taskrail.application import input_revision

        plan = dict(summary="Existing draft")
        flow = dict(stage="plan-reviewer", plan=plan)
        state = dict(status="RUNNING", requirements=[], results=dict(plan="01-plan/result.json"))
        verdict = dict(summary="Missing condition", sources=[dict(field="goal", quote="condition")])
        for attempt in range(3):
            flow.update(stage="plan-reviewer", plan=plan)
            state["results"]["plan"] = "01-plan/result.json"
            input_revision.route(flow, state, verdict, "same entire plan")
            self.assertEqual(state["status"], "NO_PROGRESS" if attempt == 2 else "RUNNING")
        self.assertEqual(flow["plan"], plan)
        self.assertEqual(state["results"]["plan"], "01-plan/result.json")

    def test_accepted_input_quotes_are_not_rewritten_as_workspace_paths(self):
        from pathlib import Path

        from taskrail.application.artifacts import rendered

        payload = dict(status="UNDERSTOOD", requirements=[dict(text="Inspect project/file.py")])
        self.assertEqual(rendered(payload, dict(project=Path("/isolated"))), payload)


class UnderstandingWorkflowTests(LiveFixture, unittest.TestCase):
    def test_planner_can_return_a_missing_obligation_to_understanding(self):
        self.check_revision("planner")

    def test_plan_reviewer_can_return_a_missing_obligation_to_understanding(self):
        self.check_revision("plan-reviewer")

    def check_revision(self, stage):
        original = self.task.read_text().replace("Return 2", "Return 2. Preserve the comment.")
        self.task.write_text(original)
        run, status, state = self.run_mode(f"input-revision-{stage}")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        interpretation = [row for row in state["stages"] if row["stage"] == "understanding"]
        self.assertEqual(len(interpretation), 2)
        before, after = [
            json.loads((run / row["directory"] / "result.json").read_text())
            for row in interpretation
        ]
        self.assertEqual(before["requirements"][0], after["requirements"][0])
        self.assertEqual(len(after["requirements"]), 2)
        self.assertEqual(after["requirements"][1]["kind"], "constraint")
        second = json.loads(
            (run / interpretation[1]["directory"] / "request.md").read_text().split("Context:\n")[1]
        )
        self.assertEqual(
            second["feedback"]["input_correction"]["sources"][0]["quote"], "Preserve the comment."
        )
        self.assertEqual((run / "00-input/task.md").read_text(), original)
        names = [row["stage"] for row in state["stages"]]
        self.assertEqual(
            names[-5:], ["planner", "plan-reviewer", "implementer", "check", "reviewer"]
        )

    def test_understanding_precedes_planning_and_exact_reference_errors_stay_in_session(self):
        run, status, state = self.run_mode("understanding-invalid")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(
            [entry["stage"] for entry in state["stages"][:2]], ["understanding", "planner"]
        )
        self.assertEqual(state["stages"][0]["result_corrections"], 1)
        self.assertEqual(state["stages"][0]["session_turns"], 2)
        accepted = json.loads((run / state["results"]["understanding"]).read_text())
        self.assertEqual(accepted["requirements"], state["requirements"])
        request = (run / "01-understand/request.md").read_text()
        self.assertNotIn("source_packet", request)
        self.assertNotIn("PROJECT MAP", request)

    def test_continue_preserves_accepted_requirements_and_starts_at_failed_stage(self):
        from taskrail.application.live import execute_task

        run, status, state = self.run_mode("review-timeout", transport_retries=0)
        self.assertEqual(status, "TIMEOUT")
        accepted = copy.deepcopy(state["requirements"])
        count = len(state["stages"])
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        settings["timeout_seconds"] = 5
        self.settings.write_text(json.dumps(settings))
        _, status = execute_task(run / "00-input/task.md", self.settings, run_dir=run, resume=True)
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(state["requirements"], accepted)
        self.assertEqual([row["stage"] for row in state["stages"][count:]], ["reviewer"])
        self.assertEqual(state["task_spec"]["requirements"], accepted)

    def test_interpretation_model_defaults_to_planner_but_can_be_selected_separately(self):
        from taskrail.infrastructure.opencode_cli import role_models

        self.assertEqual(role_models({}), {})
        self.assertEqual(role_models(dict(planner="internal/a"))["understanding"], "internal/a")
        models = dict(planner="internal/a", understanding="internal/b")
        self.assertEqual(role_models(models), models)
