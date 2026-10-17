"""Regressions from an expensive planning run and interactive deployment."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from countersign.application import instruction_sources, prompts
from countersign.core import schema

BASE = Path(__file__).resolve().parents[1]


class PlanningRegressions(unittest.TestCase):
    def payload(self):
        return dict(
            schema_version=1,
            status="BLOCKED",
            summary="Required history is unavailable",
            coverage=[],
            evidence=[],
            unverified=[],
            blocking_gaps=["Git history is required but command execution is unavailable"],
            steps=[],
            files_read=[],
            proposed_change_files=[],
        )

    def test_exact_envelope_is_presentation_only(self):
        payload = self.payload()
        encoded = json.dumps(payload)
        for response in (encoded, "```json\n" + encoded + "\n```", "```\n" + encoded + "\n```"):
            self.assertEqual(schema.decode(response, "planner"), payload)
        for response in (
            encoded + "\n" + encoded,
            "```json\n" + encoded + "\n" + encoded + "\n```",
            '```json\n{"status":"PLAN_READY","steps":["Old format"]}\n```',
            encoded.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                schema.decode(response, "planner")
        with self.assertRaisesRegex(ValueError, "Empty final response"):
            schema.decode(" \n", "planner")

    def test_roles_fail_before_model_launch_and_bundled_roles_pass(self):
        for role in instruction_sources.ROLES:
            instruction_sources.validate_role_source(BASE / "countersign/agents" / (role + ".md"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planner.md"
            path.write_text("steps MUST be a list of nonempty strings, not objects.")
            with self.assertRaisesRegex(ValueError, "Outdated role instructions.*planner.md"):
                instruction_sources.validate_role_source(path)

    def test_repair_retains_assigned_ids_without_research_permissions(self):
        requirements = [dict(id="R7", kind="task", text="Fix only the requested role")]
        request = prompts.repair(
            json.dumps(self.payload()), "bad criteria", "planner", 1, requirements
        )
        self.assertIn('"id": "R7"', request)
        self.assertIn("Do not research", request)
        self.assertIn("Missing evidence requires gap/BLOCKED", request)
        self.assertNotIn("source research", request)
        self.assertNotIn("at most 60", prompts.INSTRUCTIONS["planner"])

    def test_explicit_keep_does_not_prompt_on_terminal(self):
        for arguments, prompts_expected, expected in (
            (["--autostart=keep", "--wait=3600"], False, "keep:3600"),
            (["--autostart=yes"], False, "yes:0"),
            (["--boot=yes"], False, "yes:0"),
            ([], True, "keep:0"),
        ):
            with self.subTest(arguments=arguments):
                master, slave = os.openpty()
                try:
                    os.write(master, b"\n")
                    result = subprocess.run(
                        [
                            "bash",
                            "-c",
                            'source "$1" "${@:2}"; printf "%s:%s" "$autostart" "$wait_seconds"',
                            "options",
                            str(BASE / "deploy/options.sh"),
                            *arguments,
                        ],
                        stdin=slave,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5,
                        check=True,
                    )
                finally:
                    os.close(master)
                    os.close(slave)
                self.assertEqual(
                    "Start Countersign automatically" in result.stderr, prompts_expected
                )
                self.assertEqual(result.stdout, expected)
