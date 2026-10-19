"""Exercise approval lifetime, local execution and stage clock without real models."""

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from countersign.git import deadline, process
from countersign.interactions import access, approvals, local, transcripts
from countersign.interactions.clock import StageClock
from countersign.interactions.session import StageSession


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.root = self.run / "project"
        self.root.mkdir()
        self.context = dict(run=self.run, roots={"project": self.root}, timeout=5)

    def request(self, argv):
        return dict(
            schema_version=1,
            status="LOCAL_REQUEST",
            cwd=str(self.root),
            argv=argv,
            reason="Inspect local state",
        )

    def test_approval_has_no_expiry_and_rejects_stale_or_duplicate_decisions(self):
        received = []
        thread = threading.Thread(
            target=lambda: received.append(approvals.wait(self.run, self.request(["echo", "ok"])))
        )
        thread.start()
        self.addCleanup(thread.join, 3)
        deadline = time.monotonic() + 3
        while approvals.load(self.run) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        pending = approvals.load(self.run)
        payload = dict(id=self.run.name, ticket="old", decision="allow", alternative="")
        with self.assertRaisesRegex(ValueError, "Stale"):
            approvals.decide(self.run, payload)
        time.sleep(0.25)
        self.assertTrue(thread.is_alive())
        payload.update(
            ticket=pending["ticket"], decision="alternative", alternative="Use syntax checks only"
        )
        approvals.decide(self.run, payload)
        with self.assertRaises(ValueError):
            approvals.decide(self.run, payload)
        thread.join(3)
        self.assertEqual(received[0]["decision"], "alternative")
        self.assertIsNone(approvals.load(self.run))

    def test_wait_can_be_stopped_without_execution(self):
        (self.run / "stop.request").touch()
        with self.assertRaises(KeyboardInterrupt):
            approvals.wait(self.run, self.request(["echo", "no"]))
        self.assertIsNone(approvals.load(self.run))

    def test_real_local_output_failure_and_literal_arguments(self):
        script = "import sys; print(sys.argv[1]); sys.exit(3)"
        outcome = local.execute(
            self.request([sys.executable, "-c", script, "$(touch forbidden)"]), self.context
        )
        self.assertEqual(outcome["exit_code"], 3)
        self.assertEqual(outcome["status"], "FAILED")
        self.assertEqual(outcome["stdout"].strip(), "$(touch forbidden)")
        self.assertFalse((self.root / "forbidden").exists())

    def test_timeout_reaps_process_and_never_reports_success(self):
        self.context["timeout"] = 0.05
        with self.assertRaisesRegex(ValueError, "timed out"):
            local.execute(
                self.request([sys.executable, "-c", "import time; time.sleep(30)"]), self.context
            )

    def test_clock_excludes_only_paused_seconds(self):
        with patch("countersign.interactions.clock.time.monotonic", return_value=100):
            clock = StageClock(3600)
        with patch("countersign.interactions.clock.time.monotonic", return_value=8000):
            clock.paused = 7800
            self.assertEqual(clock.elapsed(), 100)
            self.assertEqual(clock.remaining(), 3500)

    def test_access_requires_exact_roots_and_never_grants_edits(self):
        profile = self.run / "agent.md"
        profile.write_text(
            "---\n"
            + json.dumps(
                {
                    "permission": {
                        "read": {"*": "deny"},
                        "external_directory": {"*": "deny"},
                        "edit": "deny",
                    }
                }
            )
            + "\n---\nRole instructions"
        )
        environment = dict(profile=profile, roots={"project": self.root})
        before = profile.read_text()
        answer = access.apply_all(
            environment, [dict(tool="read", input={"filePath": "/etc/passwd"})]
        )
        self.assertEqual(answer["status"], "REJECTED")
        self.assertEqual(profile.read_text(), before)
        allowed = self.root / "sample.txt"
        answer = access.apply_all(
            environment, [dict(tool="read", input={"filePath": str(allowed)})]
        )
        self.assertEqual(answer["status"], "GRANTED")
        rights = json.loads(profile.read_text()[4:].split("\n---")[0])["permission"]
        self.assertEqual(rights["edit"], "deny")
        self.assertEqual(rights["read"][str(allowed)], "allow")

    def test_transcript_evidence_is_bound_to_actual_output(self):
        stage = self.run / "01-plan"
        stage.mkdir()
        (stage / "events.jsonl").touch()
        outcome = dict(status="SUCCEEDED", exit_code=0, stdout="lint passed")
        transcripts.local_snapshot(self.run, stage, self.request(["echo", "ok"]), outcome)
        paths = transcripts.confirmed_paths(self.run)
        self.assertEqual(len(paths), 1)
        Path(next(iter(paths))).write_text("{}")
        self.assertEqual(transcripts.confirmed_paths(self.run), set())

    def test_local_decisions_resume_same_session_and_exclude_long_wait(self):
        for role in ("planner", "reviewer", "implementer"):
            for decision in ("allow", "deny", "alternative"):
                with self.subTest(role=role, decision=decision):
                    folder = self.run / f"{role}-{decision}"
                    folder.mkdir()
                    (folder / "events.jsonl").touch()
                    record = dict(role=role, directory=folder.name, budget=dict(timeout=60))
                    state = dict(stages=[record])
                    environment = dict(
                        self.context,
                        format_only=False,
                        expected={},
                        git_before={},
                        allowed=[],
                        scan=lambda: {},
                        git_metadata=lambda roots: {},
                    )
                    now = [100.0]
                    calls = []

                    def invoke(options):
                        calls.append(options)
                        now[0] += 2
                        text = json.dumps(self.request([sys.executable, "--version"]))
                        return dict(
                            status="OK",
                            sessions=["same-session"],
                            tokens=dict(total=5),
                            final_text=("Now let me run ansible-lint.\n\n" + text)
                            if len(calls) == 1
                            else "{}",
                        )

                    def decide(*_args):
                        now[0] += 7200
                        return dict(decision=decision, alternative="Inspect existing output")

                    with ExitStack() as stack:
                        stack.enter_context(
                            patch(
                                "countersign.interactions.clock.time.monotonic",
                                side_effect=lambda: now[0],
                            )
                        )
                        stack.enter_context(patch("countersign.interactions.clock.save_run"))
                        stack.enter_context(patch("countersign.interactions.session.save_run"))
                        stack.enter_context(
                            patch("countersign.interactions.session.run_agent", side_effect=invoke)
                        )
                        stack.enter_context(
                            patch("countersign.interactions.approvals.wait", side_effect=decide)
                        )
                        execute = stack.enter_context(
                            patch(
                                "countersign.interactions.local.execute",
                                return_value=dict(status="SUCCEEDED", stdout="Python", exit_code=0),
                            )
                        )
                        session = StageSession((folder, record), state, environment, {})
                        outcome = session.run()
                    self.assertEqual(outcome["status"], "OK")
                    self.assertEqual(outcome["elapsed_seconds"], 4)
                    self.assertEqual(outcome["tokens"]["total"], 10)
                    self.assertEqual(record["paused_seconds"], 7200)
                    self.assertEqual(len(state["stages"]), 1)
                    self.assertEqual(calls[1]["runtime"]["session_id"], "same-session")
                    self.assertEqual(calls[1]["timeout"], 58)
                    self.assertEqual(execute.call_count, int(decision == "allow"))
                    self.assertIn(
                        "SUCCEEDED" if decision == "allow" else "DECLINED",
                        (folder / "tool-result.md").read_text(),
                    )

    def test_missing_program_waits_for_installation_instead_of_rejecting(self):
        for installed in (False, True):
            with self.subTest(installed=installed):
                folder = self.run / f"missing-{installed}"
                folder.mkdir()
                (folder / "events.jsonl").touch()
                record = dict(role="implementer", directory=folder.name, budget=dict(timeout=60))
                environment = dict(
                    self.context,
                    format_only=False,
                    expected={},
                    git_before={},
                    allowed=[],
                    scan=lambda: {},
                    git_metadata=lambda roots: {},
                )
                responses = [
                    json.dumps(self.request(["countersign-missing-tool", "--check"])),
                    "{}",
                ]
                requests = []

                def invoke(_options):
                    text = responses.pop(0)
                    return dict(status="OK", sessions=["same"], tokens={}, final_text=text)

                def decide(_run, request):
                    requests.append(request)
                    return dict(decision="allow", alternative="")

                found = [None, "/usr/bin/countersign-missing-tool" if installed else None]
                with ExitStack() as stack:
                    stack.enter_context(patch("countersign.interactions.clock.save_run"))
                    stack.enter_context(patch("countersign.interactions.session.save_run"))
                    stack.enter_context(
                        patch("countersign.interactions.session.run_agent", side_effect=invoke)
                    )
                    stack.enter_context(
                        patch("countersign.interactions.approvals.wait", side_effect=decide)
                    )
                    stack.enter_context(
                        patch(
                            "countersign.interactions.local_request.shutil.which",
                            side_effect=found,
                        )
                    )
                    execute = stack.enter_context(
                        patch(
                            "countersign.interactions.local.execute",
                            return_value=dict(status="SUCCEEDED", stdout="ok", exit_code=0),
                        )
                    )
                    StageSession((folder, record), dict(stages=[record]), environment, {}).run()
                self.assertIn("not installed on the orchestrator host", requests[0]["notice"])
                self.assertEqual(execute.call_count, int(installed))
                result = (folder / "tool-result.md").read_text()
                self.assertIn("SUCCEEDED" if installed else "still not installed", result)

    def test_expired_git_stage_never_starts_a_process(self):
        with deadline.Deadline(0, self.run):
            with patch("countersign.git.transport.subprocess.Popen") as launch:
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.invoke(self.root, ["status"])
                launch.assert_not_called()

    def test_local_request_envelopes_preserve_arguments_and_reject_ambiguity(self):
        payload = self.request([sys.executable, "--version"])
        encoded = json.dumps(payload)
        for text in (encoded, "Now run the check.\n" + encoded, "```json\n" + encoded + "\n```"):
            self.assertEqual(local.extract(text), payload)
        for text in (
            encoded + "\n" + encoded,
            "[" + encoded + "]",
            encoded[:-1],
            encoded.replace('"status":', '"status": "LOCAL_REQUEST", "status":'),
        ):
            self.assertIsNone(local.extract(text))
        with self.assertRaisesRegex(ValueError, "Invalid local request"):
            local.extract(json.dumps(dict(payload, steps=[])))
