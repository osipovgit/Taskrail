"""Attempts keep provenance across repeated launches."""

import tempfile
import unittest
from pathlib import Path

from taskrail.application import attempt_context


class AttemptProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)

    def record(self, number, stage="planner"):
        record = dict(directory=f"{number:02d}-plan", stage=stage, mode="model")
        (self.run / record["directory"]).mkdir()
        return record

    def test_provenance_uses_recorded_role_source(self):
        inputs = self.run / "00-input"
        inputs.mkdir()
        record = dict(self.record(1), role="planner")
        state = {
            "agent_sources": {"planner": "saved-hash"},
            "contract_sha256": "sealed-contract",
            "run_format": 3,
            "agent_source_directory": str(inputs / "agents"),
        }
        config = dict(timeout=60)
        for _ in range(8):
            attempt_context.prepare(record, config, state)
            self.assertEqual(record["timeout_seconds"], 60)
            self.assertEqual(record["contract_sha256"], "sealed-contract")
        self.assertEqual(record["agent_source"], str(inputs / "agents/planner.md"))
        self.assertEqual(record["agent_sha256"], "saved-hash")
