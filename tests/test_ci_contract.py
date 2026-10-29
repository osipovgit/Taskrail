"""Merge gates must fail when required work is missing or unsuccessful."""

import contextlib
import io
import json
import os
import shlex
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import yaml

from taskrail import cli_service

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
STATES = ("success", "failure", "cancelled", "skipped", "timed_out", "")


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def run_gate(document, **environment):
    script = document["jobs"]["gate"]["steps"][0]["run"]
    return subprocess.run(
        ["bash", "-e", "-c", script],
        env=dict(os.environ, **environment),
        capture_output=True,
        text=True,
        timeout=10,
    ).returncode


class MergeGateTests(unittest.TestCase):
    def test_compatibility_workflow_uses_supported_initialization_arguments(self):
        steps = workflow("ci.yml")["jobs"]["opencode"]["steps"]
        command = next(
            line
            for step in steps
            for line in step.get("run", "").splitlines()
            if line.startswith("python -m taskrail init ")
        )
        arguments = shlex.split(command)[3:]
        with (
            mock.patch("taskrail.onboarding.init", return_value="/fixture/settings.json") as init,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli_service.init_command(arguments), 0)
        init.assert_called_once_with("$(command -v opencode)", [], force=False)

    def test_gates_wait_for_every_job_even_after_failure(self):
        for name in ("ci.yml", "codeql.yml"):
            with self.subTest(workflow=name):
                document = workflow(name)
                jobs = document["jobs"]
                gate = jobs["gate"]
                self.assertEqual(gate["if"], "always()")
                self.assertEqual(set(gate["needs"]), set(jobs) - {"gate"})
                self.assertIn("pull_request", document["on"])
                self.assertEqual(document["on"]["pull_request"], "")

    def test_ci_rejects_each_unsuccessful_required_group(self):
        document = workflow("ci.yml")
        groups = document["jobs"]["gate"]["needs"]
        for group in groups:
            for state in STATES:
                with self.subTest(group=group, state=state):
                    results = {name: {"result": "success"} for name in groups}
                    results[group]["result"] = state
                    passed = run_gate(document, RESULTS=json.dumps(results)) == 0
                    self.assertEqual(passed, state == "success")
        self.assertNotEqual(run_gate(document, RESULTS="{}"), 0)

    def test_security_requires_public_analysis_and_verified_visibility(self):
        document = workflow("codeql.yml")
        for public in ("true", "false", ""):
            for state in STATES:
                with self.subTest(public=public, state=state):
                    passed = (
                        run_gate(document, VISIBILITY="success", PUBLIC=public, ANALYSIS=state) == 0
                    )
                    expected = (public, state) in {("true", "success"), ("false", "skipped")}
                    self.assertEqual(passed, expected)
        for visibility in STATES[1:]:
            with self.subTest(visibility=visibility):
                self.assertNotEqual(
                    run_gate(document, VISIBILITY=visibility, PUBLIC="false", ANALYSIS="skipped"),
                    0,
                )
