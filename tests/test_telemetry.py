import json
import sys
import tempfile
import unittest
from pathlib import Path

from taskrail.infrastructure.runner import run_agent
from taskrail.observability.telemetry import Telemetry


class TelemetryTests(unittest.TestCase):
    def test_usage_deduplication_and_compaction_evidence(self):
        t = Telemetry()
        finish = dict(
            type="step_finish",
            part=dict(
                id="s",
                tokens=dict(
                    total=100, input=80, output=20, reasoning=5, cache=dict(read=10, write=0)
                ),
            ),
        )
        for event in (finish, finish, dict(type="text", part=dict(text="I compacted the context"))):
            t.observe(json.dumps(event))
        value = t.summary()
        self.assertEqual(value["tokens"]["total"], 100)
        self.assertEqual(t.timeline.compactions, [])
        t.observe(json.dumps(dict(type="session.compacted", timestamp=123)))
        self.assertEqual(len(t.timeline.compactions), 1)
        self.assertNotIn("compaction_completed", t.summary())

    def test_tool_trace_preserves_arguments_status_errors_and_timing(self):
        t = Telemetry()
        for i in range(2):
            t.observe(
                json.dumps(
                    dict(
                        type="tool_use",
                        timestamp=2500,
                        part=dict(
                            id=str(i),
                            tool="read",
                            callID=str(i),
                            state=dict(
                                status="completed",
                                input=dict(filePath="/repo/file"),
                                output="x" * 9000,
                                time=dict(start=1000, end=2500),
                            ),
                        ),
                    )
                )
            )
        value = t.summary()
        self.assertEqual(value["tool_calls"], 2)
        self.assertEqual(value["repeated_reads"], 1)
        self.assertEqual(value["timeline"][0]["duration_seconds"], 1.5)
        self.assertTrue(value["timeline"][0]["output_truncated"])
        self.assertEqual(value["usage_coverage"], "unavailable")
        self.assertIsNone(value["reported_cost"])

    def test_observed_budget_stops_run_and_keeps_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "fake.py"
            event = dict(
                type="step_finish",
                part=dict(id="usage", tokens=dict(total=100, input=80, output=20)),
            )
            script.write_text(
                "import time\nprint(" + repr(json.dumps(event)) + ", flush=True)\ntime.sleep(10)\n"
            )
            prompt = root / "task.md"
            prompt.write_text("Test")
            value = run_agent(
                dict(
                    command=[sys.executable, str(script)],
                    workspace=root,
                    agent="a",
                    model="m",
                    prompt=prompt,
                    attempt=root / "attempt",
                    timeout=20,
                    runtime=dict(token_budget=50),
                )
            )
            self.assertEqual(value["status"], "TOKEN_BUDGET_EXCEEDED")
            self.assertEqual(value["tokens"]["total"], 100)
            self.assertTrue((root / "attempt/telemetry.json").exists())
