"""Evidence feedback cannot authorize unread views or repeat unsuccessful planner research."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail.application import citation_review, evidence, source_guidance, source_views
from taskrail.application.attempt_retries import Retries


class EvidenceRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.run = self.base / "run"
        self.run.mkdir()
        self.source = self.root / "report.json"
        self.source.write_text(
            json.dumps([dict(rule="test", line=number) for number in range(100)])
        )
        self.context = dict(run=self.run, roots=dict(project=self.root))
        self.claim = dict(id="E1", path=str(self.source), line_start=1, line_end=1)

    def test_missing_json_creates_view_but_does_not_attest_any_read(self):
        with self.assertRaisesRegex(ValueError, "lossless formatted source view") as rejected:
            citation_review.validate([self.claim], [], self.context)
        view = source_views.prepare(self.run, self.source, self.context["roots"])
        self.assertIn(view["path"], str(rejected.exception))
        self.assertEqual(evidence.validation_records(self.run), [])
        claim = dict(self.claim, path=view["path"], line_start=2, line_end=4)
        with self.assertRaisesRegex(ValueError, "matching observed read"):
            citation_review.validate([claim], [], self.context)
        lines = Path(view["path"]).read_text().splitlines()[1:4]
        record = dict(
            tool="read",
            input=dict(filePath=view["path"]),
            output="\n".join(f"{number}: {line}" for number, line in enumerate(lines, 2)),
            source_sha256=view["view_sha256"],
            source_event="trace.jsonl",
            event_line=1,
        )
        proof = citation_review.validate([claim], [record], self.context)[0]
        self.assertEqual(proof["source_view"]["source_sha256"], evidence.fingerprint(self.source))
        self.source.write_text(self.source.read_text().replace('"test"', '"changed"'))
        with self.assertRaises(ValueError):
            citation_review.validate([claim], [record], self.context)

    def test_multiple_bad_citations_are_reported_together(self):
        text = self.root / "issues.txt"
        text.write_text("first\nsecond\n")
        claims = [dict(self.claim, path=str(text)), dict(self.claim, id="E2")]
        with self.assertRaises(ValueError) as rejected:
            citation_review.validate(claims, [], self.context)
        error = str(rejected.exception)
        self.assertIn("Evidence E1", error)
        self.assertIn("Evidence E2", error)
        self.assertIn("source-views", error)

    def test_explicit_inputs_get_only_safe_view_pointers(self):
        config = dict(
            roots=self.context["roots"],
            task_spec=dict(fields=[dict(name="entry_points", text="project/report.json")]),
        )
        hints = source_guidance.inputs(config, None, self.run)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["source_path"], str(self.source))
        self.assertEqual(set(hints[0]), {"source_path", "path", "lines"})
        self.assertEqual(evidence.validation_records(self.run), [])
        plan = dict(evidence=[dict(self.claim, path=hints[0]["path"])])
        config["task_spec"]["fields"][0]["text"] = ""
        self.assertEqual(source_guidance.inputs(config, plan, self.run), hints)
        config["task_spec"]["fields"][0]["text"] = "The report.json should be considered."
        self.assertEqual(source_guidance.inputs(config, None, self.run), [])

    def test_repeated_planner_error_does_not_start_fresh_research(self):
        workflow = SimpleNamespace(flow=dict(stage="planner"), state=dict(stages=[]), config={})
        retries = Retries(SimpleNamespace(workflow=workflow))
        outcome = dict(status="INVALID_RESULT", contract_error="Missing evidence")
        with patch.object(retries, "result_repair", return_value=True) as repair:
            self.assertTrue(retries.allowed(outcome))
            repair.assert_called_once()
            outcome["validation_errors"] = ["Missing evidence"]
            repair.reset_mock()
            self.assertFalse(retries.allowed(outcome))
            repair.assert_not_called()
            outcome["contract_error"] = "Different defect"
            self.assertTrue(retries.allowed(outcome))

    def test_an_invalid_review_gets_one_full_attempt_and_the_implementer_none(self):
        error = "review.md: line 5: R1 needs its reason"
        for stage, repaired in (("reviewer", True), ("implementer", False)):
            with self.subTest(stage=stage):
                workflow = SimpleNamespace(
                    run=self.run,
                    flow=dict(stage=stage),
                    state=dict(stages=[dict(directory="01-review")], requirements=[]),
                    config={},
                )
                attempts = SimpleNamespace(workflow=workflow, request="Original task")
                retries = Retries(attempts)
                outcome = dict(status="INVALID_RESULT", contract_error=error, final_text="DONE")
                self.assertEqual(retries.allowed(outcome), repaired)
                self.assertEqual(error in attempts.request, repaired)
                self.assertFalse(retries.allowed(outcome))

    def test_repeated_ranges_prepare_each_source_view_once(self):
        second = self.root / "other.json"
        second.write_bytes(self.source.read_bytes())
        config = dict(roots=self.context["roots"])
        claims = [dict(self.claim, line_end=number) for number in range(1, 7)]
        claims.append(dict(self.claim, path=str(second)))
        prepare = source_views.prepare
        with patch.object(source_views, "prepare", wraps=prepare) as create:
            hints = source_guidance.inputs(config, dict(evidence=claims), self.run)
            self.assertEqual(len(hints), 2)
            self.assertEqual(create.call_count, 2)
        with patch.object(source_views, "prepare", wraps=prepare) as create:
            with self.assertRaises(ValueError):
                citation_review.validate(claims, [], self.context)
            self.assertEqual(create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
