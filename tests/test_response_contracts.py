"""Response envelopes, role contracts and installer prompts."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from taskrail.application import instruction_sources
from taskrail.core import json_response, schema

BASE = Path(__file__).resolve().parents[1]


def decoded(response):
    """One unambiguous object in the planner's stored shape."""
    payload = json_response.extract(response, schema.unique_fields)
    schema.validate(payload, schema.SCHEMAS["planner"])
    return payload


class ResponseContractTests(unittest.TestCase):
    def payload(self):
        return dict(
            schema_version=1,
            status="BLOCKED",
            decision="blocked",
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
            self.assertEqual(decoded(response), payload)
        for response in (
            encoded + "\n" + encoded,
            "```json\n" + encoded + "\n" + encoded + "\n```",
            '```json\n{"status":"PLAN_READY","steps":["Old format"]}\n```',
            encoded.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                decoded(response)

    def test_roles_fail_before_model_launch_and_bundled_roles_pass(self):
        for role in instruction_sources.ROLES:
            instruction_sources.validate_role_source(BASE / "taskrail/agents" / (role + ".md"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planner.md"
            path.write_text("steps MUST be a list of nonempty strings, not objects.")
            with self.assertRaisesRegex(ValueError, "Outdated role instructions.*planner.md"):
                instruction_sources.validate_role_source(path)

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
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=True,
                    )
                finally:
                    os.close(master)
                    os.close(slave)
                self.assertEqual("Start Taskrail automatically" in result.stderr, prompts_expected)
                self.assertEqual(result.stdout, expected)
