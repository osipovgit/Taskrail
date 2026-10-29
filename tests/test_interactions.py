"""Exercise approval lifetime, local execution and stage clock without real models."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sandbox_fixture import without_sandbox

from taskrail.core import protected_paths
from taskrail.git import deadline, process
from taskrail.interactions import (
    access,
    approval_policy,
    approvals,
    local,
    local_request,
    local_route,
    read_only,
    transcripts,
)
from taskrail.interactions.clock import StageClock
from taskrail.interactions.session import StageSession


class InteractionTests(unittest.TestCase):
    def setUp(self):
        without_sandbox(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "run"
        self.run.mkdir()
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

    def test_allow_all_on_a_card_approves_later_requests_with_a_ledger(self):
        state = {}
        card = dict(decision="allow", alternative="", allow_all=True)
        with patch("taskrail.interactions.approvals.wait", return_value=card) as wait:
            first = approval_policy.decision(self.run, self.request(["echo", "1"]), state)
            second = approval_policy.decision(self.run, self.request(["echo", "2"]), state)
        self.assertEqual(wait.call_count, 1)
        self.assertEqual(first["decision"], "allow")
        self.assertTrue(second["automatic"])
        self.assertTrue(state["auto_approve"])
        ledger = [json.loads(path.read_text()) for path in self.run.glob("approval-*.json")]
        self.assertEqual(ledger[0]["request"]["request"]["argv"], ["echo", "2"])
        self.assertIsNone(approvals.load(self.run))

    def test_inline_shell_or_python_code_is_named_on_its_card(self):
        inline = (
            ["bash", "-c", "id"],
            ["sh", "-ec", "id"],
            ["/usr/bin/python3", "-Ic", "1"],
            ["env", "FOO=1", "bash", "-c", "id"],
            ["timeout", "5", "sh", "-c", "id"],
            ["env", "-S", "python3 -c 1"],
            ["/usr/bin/env", "-vS", "/usr/bin/python3 -c print(987654)"],
            ["env", "--split-string=python3\\_-c\\_1"],
            ["bash", "--rcfile", "/dev/null", "-c", "printf harmless"],
            ["bash", "--init-file", "/dev/null", "-mc", "printf harmless"],
            ["bash", "-m", "-c", "printf harmless"],
            ["bash", "-eo", "pipefail", "-c", "printf harmless"],
            ["python3", "--check-hash-based-pycs", "never", "-c", "print(1)"],
            ["python3", "-W", "ignore", "-X", "dev", "-c", "print(1)"],
            ["python3", "--check-hash-based-pycs"],
            ["timeout", "5", "bash", "--rcfile", "/dev/null", "-c", "printf harmless"],
            ["xargs", "python3", "--future-option", "value", "-c", "print(1)"],
        )
        scripts = (
            ["bash", "x.sh"],
            [
                "bash",
                "--noprofile",
                "--norc",
                "--rcfile",
                "/dev/null",
                "script with spaces.sh",
                "-c",
            ],
            ["python3", "-Wignore", "-Xdev", "script with spaces.py", "-c"],
            ["python3", "--check-hash-based-pycs", "never", "-m", "pytest", "-c", "x.ini"],
            ["python3", "-m", "pytest", "-c", "x.ini"],
            ["ls", "-c"],
        )
        for argv in (*inline, *scripts):
            with self.subTest(argv=argv):
                approve = MagicMock(return_value=dict(decision="deny", alternative=""))
                session = SimpleNamespace(
                    active=(self.run, dict(role="reviewer")), environment=self.context
                )
                actions = SimpleNamespace(
                    session=session,
                    run=self.run,
                    folder=self.run,
                    approve=approve,
                    local_result=lambda payload, answer: answer,
                )
                local_route.local_action(actions, self.request(argv))
                self.assertNotIn("personal", approve.call_args.kwargs)
                notice = approve.call_args.args[0].get("notice", "")
                self.assertEqual("review the whole script" in notice, argv in inline)
        state = dict(auto_approve=True)
        card = dict(decision="allow", alternative="")
        with patch("taskrail.interactions.approvals.wait", return_value=card) as wait:
            request = self.request(["bash", "-c", "id"])
            answer = approval_policy.decision(self.run, request, state, personal=True)
        wait.assert_called_once()
        self.assertNotIn("automatic", answer)

    def test_listing_commands_inside_the_roots_need_no_decision(self):
        roots = {"project": self.root}
        (self.root / "roles").mkdir()
        (self.root / "roles/main.yml").write_text("- name: x\n")
        (self.root / ".env").write_text("TOKEN=secret\n")
        (self.root / "outside").symlink_to("/etc")
        allowed = [
            ["ls", "-la", "roles"],
            ["find", ".", "-name", "*.yml", "-type", "f"],
            ["find", "--", ".", "-maxdepth", "2", "-name", "*.yml", "-print"],
            ["head", "-n", "20", "roles/main.yml"],
            ["head", "-n20", "roles/main.yml"],
            ["grep", "-n", "name", "roles/main.yml"],
            ["grep", "-e", "/etc/passwd", "roles/main.yml"],
            ["grep", "--color", "name", "roles/main.yml"],
            ["grep", "--color=never", "name", "roles/main.yml"],
            ["ls", "--color", "roles"],
            ["ls", "--color=never", "roles"],
            ["wc", "-l", "--", "roles/main.yml"],
            ["du", "-sh"],
        ]
        refused = [
            ["cat", ".env"],
            ["cat", "/etc/passwd"],
            ["ls", "outside"],
            ["find", ".", "-exec", "rm", "{}", ";"],
            ["find", ".", "-delete"],
            ["find", "--", ".", "-delete"],
            ["find", "--", ".", "-fprint", "output"],
            ["find", "--", ".", "-exec", "touch", "marker", ";"],
            ["find", ".", "-name", "*.yml", "-unknown"],
            ["head", "--unknown", "roles/main.yml"],
            ["wc", "--files0-from", "roles/main.yml"],
            ["ls", "--dereference-command-line", "outside"],
            ["ls", "--color", "/etc"],
            ["grep", "--color", "name", "/etc/passwd"],
            ["grep", "--color=never", "name", "/etc/passwd"],
            ["grep", "-rn", "TOKEN", "."],
            ["grep", "--file=/etc/shadow", "roles/main.yml"],
            ["tail", "-f", "roles/main.yml"],
            ["ls", "-L", "roles"],
            ["ansible-lint", "roles"],
            ["/bin/ls", "roles"],
        ]
        for argv in allowed:
            with self.subTest(argv=argv):
                self.assertTrue(read_only.command(self.request(argv), roots))
        for argv in refused:
            with self.subTest(argv=argv):
                self.assertFalse(read_only.command(self.request(argv), roots))
        state = {}
        with patch("taskrail.interactions.approvals.wait") as wait:
            scope = (roots, protected_paths.DEFAULT_PATTERNS)
            answer = approval_policy.decision(self.run, self.request(["ls"]), state, scope)
        wait.assert_not_called()
        self.assertEqual((answer["decision"], answer["rule"]), ("allow", "read_only"))
        read = dict(tool="read", input=dict(filePath=str(self.root / "roles/main.yml")))
        secret = dict(tool="read", input=dict(filePath=str(self.root / ".env")))
        self.assertTrue(read_only.reads([read], roots))
        self.assertFalse(read_only.reads([read, secret], roots))

    def test_allow_all_can_be_revoked_and_restored_on_a_card(self):
        state = dict(auto_approve=True)
        approval_policy.revoke(self.run)
        self.assertFalse(approval_policy.active(self.run, state))
        self.assertFalse(approval_policy.at_start(self.run, dict(auto_approve=True)))
        card = dict(decision="allow", alternative="", allow_all=True)

        def personal_decision(run, request):
            (run / approvals.PENDING).write_text(json.dumps(dict(ticket="restore")))
            approvals.decide(run, dict(card, id=run.name, ticket="restore"))
            approvals.clear(run)
            return card

        with patch("taskrail.interactions.approvals.wait", side_effect=personal_decision) as wait:
            approval_policy.decision(self.run, self.request(["make"]), state)
            approval_policy.decision(self.run, self.request(["make"]), state)
        self.assertEqual(wait.call_count, 1)
        self.assertTrue(approval_policy.active(self.run, state))

    def test_optional_color_argument_cannot_hide_an_outside_path(self):
        outside = self.run / "outside.txt"
        outside.write_text("test-marker\n")
        for argv in (
            ["grep", "--color", "test-marker", str(outside)],
            ["ls", "--color", str(outside)],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(read_only.command(self.request(argv), self.context["roots"]))
                # Demonstrate the actual optional-argument semantics only on disposable data.
                observed = subprocess.run(
                    argv, cwd=self.root, capture_output=True, text=True, check=True
                )
                self.assertTrue(observed.stdout)
        self.assertEqual(outside.read_text(), "test-marker\n")

    def test_path_check_does_not_depend_on_gnu_option_permutation(self):
        outside = self.run / "outside.txt"
        outside.write_text("test-marker\n")
        (self.root / "inside.txt").write_text("inside\n")
        argv = ["grep", "test-marker", "inside.txt", "-e", str(outside)]
        self.assertFalse(read_only.command(self.request(argv), self.context["roots"]))
        observed = subprocess.run(
            argv,
            cwd=self.root,
            env={"POSIXLY_CORRECT": "1"},
            capture_output=True,
            text=True,
        )
        self.assertIn(str(outside) + ":test-marker", observed.stdout)

    def test_allow_all_needs_an_allow_decision_and_a_boolean(self):
        payload = dict(id="run", ticket="t", decision="deny", alternative="", allow_all=True)
        state = {}
        with patch("taskrail.interactions.approvals.wait", return_value=payload):
            approval_policy.decision(self.run, self.request(["echo", "1"]), state)
        self.assertNotIn("auto_approve", state)
        approvals.validate_decision(payload)
        with self.assertRaisesRegex(ValueError, "boolean"):
            approvals.validate_decision(dict(payload, allow_all="yes"))

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

    def test_automatic_listings_ignore_path_shadowing_and_recheck_read_scope(self):
        shadow = self.run / "bin"
        shadow.mkdir()
        fake = shadow / "ls"
        fake.write_text("#!/bin/sh\nprintf shadow-executed\n")
        fake.chmod(0o755)
        target = self.root / "listed.txt"
        target.write_text("safe\n")
        request = self.request(["ls", "listed.txt"])
        with patch.dict(os.environ, {"PATH": str(shadow)}):
            scope = (self.context["roots"], protected_paths.DEFAULT_PATTERNS)
            decision = approval_policy.decision(self.run, request, {}, scope)
            self.assertEqual(decision["rule"], "read_only")
            context = dict(self.context, automatic_read=True)
            result = local.execute(request, context)
            self.assertEqual(result["stdout"], "listed.txt\n")
            self.assertEqual(
                local.validate(self.request(["ls", "--unknown"]), self.context["roots"])[0],
                str(fake),
            )
            target.unlink()
            target.symlink_to(self.run / "outside.txt")
            with self.assertRaisesRegex(ValueError, "no longer qualifies"):
                local.execute(request, context)
            fake.unlink()
            self.assertEqual(local_request.missing_executable(["ls"]), "ls")
            self.assertIsNone(local_request.missing_executable(["ls"], automatic=True))

    def test_timeout_reaps_process_and_never_reports_success(self):
        self.context["timeout"] = 0.05
        with self.assertRaisesRegex(ValueError, "timed out"):
            local.execute(
                self.request([sys.executable, "-c", "import time; time.sleep(30)"]), self.context
            )

    def test_clock_excludes_only_paused_seconds(self):
        with patch("taskrail.interactions.clock.time.monotonic", return_value=100):
            clock = StageClock(3600)
        with patch("taskrail.interactions.clock.time.monotonic", return_value=8000):
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

    def test_long_output_is_readable_line_by_line(self):
        stage = self.run / "01-plan"
        stage.mkdir()
        (stage / "events.jsonl").touch()
        lines = "".join(
            f"roles/web/tasks/main.yml:{number}: name[missing]\n" for number in range(3000)
        )
        outcome = dict(status="SUCCEEDED", exit_code=0, stdout=lines, stderr="")
        response = transcripts.local_snapshot(self.run, stage, self.request(["lint"]), outcome)
        text_file = self.run / "00-input/local/01-plan-0.stdout.txt"
        self.assertEqual(text_file.read_text(), lines)
        self.assertIn(f"Full output files: {text_file}", response)
        self.assertFalse((self.run / "00-input/local/01-plan-0.stderr.txt").exists())

    def test_local_decisions_resume_same_session_and_exclude_long_wait(self):
        for role in ("planner", "reviewer", "implementer"):
            for decision in ("allow", "deny", "alternative"):
                with self.subTest(role=role, decision=decision):
                    folder = self.run / f"{role}-{decision}"
                    folder.mkdir()
                    (self.run / "local-actions.json").unlink(missing_ok=True)
                    (self.run / "request-counts.json").unlink(missing_ok=True)
                    (folder / "events.jsonl").touch()
                    record = dict(
                        stage=role, role=role, directory=folder.name, budget=dict(timeout=60)
                    )
                    state = dict(stages=[record])
                    environment = dict(
                        self.context,
                        expected={},
                        git_before={},
                        allowed=[],
                        scan=lambda: {},
                        git_metadata=lambda roots: {},
                    )
                    now = [100.0]
                    calls = []

                    def invoke(options, *, calls=calls, now=now):
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

                    def decide(*_args, now=now, decision=decision):
                        now[0] += 7200
                        return dict(decision=decision, alternative="Inspect existing output")

                    with ExitStack() as stack:
                        stack.enter_context(
                            patch(
                                "taskrail.interactions.clock.time.monotonic",
                                side_effect=lambda *, now=now: now[0],
                            )
                        )
                        stack.enter_context(patch("taskrail.interactions.clock.save_run"))
                        stack.enter_context(patch("taskrail.interactions.session.save_run"))
                        stack.enter_context(
                            patch("taskrail.interactions.session.run_agent", side_effect=invoke)
                        )
                        stack.enter_context(
                            patch("taskrail.interactions.approvals.wait", side_effect=decide)
                        )
                        execute = stack.enter_context(
                            patch(
                                "taskrail.interactions.local.execute",
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
                record = dict(
                    stage="implementer",
                    role="implementer",
                    directory=folder.name,
                    budget=dict(timeout=60),
                )
                environment = dict(
                    self.context,
                    expected={},
                    git_before={},
                    allowed=[],
                    scan=lambda: {},
                    git_metadata=lambda roots: {},
                )
                responses = [
                    json.dumps(self.request(["taskrail-missing-tool", "--check"])),
                    "{}",
                ]
                requests = []
                installed_now = [False]

                def invoke(_options, *, responses=responses):
                    text = responses.pop(0)
                    return dict(status="OK", sessions=["same"], tokens={}, final_text=text)

                def decide(
                    _run, request, *, requests=requests, flag=installed_now, value=installed
                ):
                    requests.append(request)
                    flag[0] = value
                    return dict(decision="allow", alternative="")

                def found(*_args, installed_now=installed_now, **_kwargs):
                    return "/usr/bin/taskrail-missing-tool" if installed_now[0] else None

                with ExitStack() as stack:
                    stack.enter_context(patch("taskrail.interactions.clock.save_run"))
                    stack.enter_context(patch("taskrail.interactions.session.save_run"))
                    stack.enter_context(
                        patch("taskrail.interactions.session.run_agent", side_effect=invoke)
                    )
                    stack.enter_context(
                        patch("taskrail.interactions.approvals.wait", side_effect=decide)
                    )
                    stack.enter_context(
                        patch(
                            "taskrail.interactions.local_request.shutil.which",
                            side_effect=found,
                        )
                    )
                    execute = stack.enter_context(
                        patch(
                            "taskrail.interactions.local.execute",
                            return_value=dict(status="SUCCEEDED", stdout="ok", exit_code=0),
                        )
                    )
                    StageSession((folder, record), dict(stages=[record]), environment, {}).run()
                self.assertIn("not installed on the orchestrator host", requests[0]["notice"])
                self.assertEqual(execute.call_count, int(installed))
                result = (folder / "tool-result.md").read_text()
                self.assertIn("SUCCEEDED" if installed else "still not installed", result)

    def test_incomplete_local_request_returns_to_the_same_session(self):
        folder = self.run / "incomplete"
        folder.mkdir()
        (folder / "events.jsonl").touch()
        record = dict(
            stage="planner", role="planner", directory=folder.name, budget=dict(timeout=60)
        )
        environment = dict(
            self.context,
            expected={},
            git_before={},
            allowed=[],
            scan=lambda: {},
            git_metadata=lambda roots: {},
        )
        near_miss = dict(cwd=str(self.root), argv=["ansible-lint", "."], reason="Lint")
        responses = [f"LOCAL_REQUEST\n{json.dumps(near_miss)}"] * 3 + ["{}"]
        prompts = []

        def invoke(options):
            prompt = options.get("prompt")
            prompts.append(prompt.read_text() if prompt else "initial")
            return dict(status="OK", sessions=["same"], tokens={}, final_text=responses.pop(0))

        with ExitStack() as stack:
            stack.enter_context(patch("taskrail.interactions.clock.save_run"))
            stack.enter_context(patch("taskrail.interactions.session.save_run"))
            stack.enter_context(
                patch("taskrail.interactions.session.run_agent", side_effect=invoke)
            )
            execute = stack.enter_context(patch("taskrail.interactions.local.execute"))
            outcome = StageSession((folder, record), dict(stages=[record]), environment, {}).run()
        self.assertEqual(execute.call_count, 0)
        self.assertEqual(len(prompts), 3)
        self.assertIn('"status": "LOCAL_REQUEST"', prompts[1])
        self.assertIn("nothing was executed", prompts[2])
        self.assertIn("ansible-lint", outcome["final_text"])

    def test_local_cwd_may_be_a_directory_inside_a_declared_root(self):
        from taskrail.interactions import local_request

        inner = self.root / "ansible-playbooks"
        inner.mkdir()
        roots = {"project": self.root}
        request = dict(cwd=str(inner), argv=["true"], reason="Run inside a subdirectory")
        self.assertEqual(local_request.checked_request(request, roots), ["true"])
        (self.root / "escape").symlink_to(self.run, target_is_directory=True)
        for cwd in (str(self.run), str(self.root / "escape"), "relative", str(self.root / "none")):
            with self.subTest(cwd=cwd), self.assertRaises(ValueError):
                local_request.checked_request(dict(request, cwd=cwd), roots)

    def test_expired_git_stage_never_starts_a_process(self):
        with (
            deadline.Deadline(0, self.run),
            patch("taskrail.git.transport.subprocess.Popen") as launch,
        ):
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
