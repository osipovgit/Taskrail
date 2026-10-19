"""Totals across runs for the analytics view and CLI."""

import json
import tempfile
import unittest
from pathlib import Path

from countersign.web.analytics import analytics


def stage(name, status, **details):
    return dict(stage=name, status=status, mode=details.pop("mode", "model"), **details)


class AnalyticsTests(unittest.TestCase):
    def test_runs_models_and_stages_are_summed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            runs = {
                "a": dict(
                    status="READY_FOR_REVIEW",
                    metrics=dict(elapsed_seconds=10, tokens=dict(total=100)),
                    continuations=[{}],
                    stages=[
                        stage("planner", "INVALID_RESULT", model="p/m", tokens=dict(total=40)),
                        stage("planner", "RESULT_VALID", model="p/m", mode="format-repair"),
                        stage("implementer", "RESULT_VALID", elapsed_seconds=5.25),
                    ],
                ),
                "b": dict(
                    status="TIMEOUT",
                    stages=[stage("reviewer", "TIMEOUT", mode="research-recovery")],
                ),
            }
            for name, state in runs.items():
                (base / name).mkdir()
                (base / name / "run.json").write_text(json.dumps(state))
            (base / ".trash/old").mkdir(parents=True)
            (base / ".trash/old/run.json").write_text(json.dumps(dict(status="READY_FOR_REVIEW")))
            (base / "broken").mkdir()
            (base / "broken/run.json").write_text("{")
            totals = analytics(base)
        self.assertEqual(totals["runs"]["count"], 2)
        self.assertEqual(totals["runs"]["success_rate"], 0.5)
        self.assertEqual(totals["runs"]["statuses"], {"READY_FOR_REVIEW": 1, "TIMEOUT": 1})
        self.assertEqual(totals["runs"]["tokens"], 100)
        self.assertEqual(totals["runs"]["continuations"], 1)
        model = totals["models"]["p/m"]
        self.assertEqual((model["attempts"], model["failed"], model["format_repairs"]), (2, 1, 1))
        self.assertEqual(model["tokens"], 40)
        self.assertEqual(totals["models"]["opencode default"]["attempts"], 2)
        self.assertEqual(totals["stages"]["reviewer"]["recoveries"], 1)
        self.assertEqual(totals["stages"]["implementer"]["elapsed_seconds"], 5.2)

    def test_empty_storage(self):
        totals = analytics(Path("/nonexistent/runs"))
        self.assertEqual(totals["runs"]["count"], 0)
        self.assertIsNone(totals["runs"]["success_rate"])


if __name__ == "__main__":
    unittest.main()
