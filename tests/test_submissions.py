import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from countersign.web.server import make_server
from countersign.web.submissions import BusyError, TaskLauncher
from countersign.web.task_form import build_task

BASE = Path(__file__).resolve().parents[1]


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.repo / "hello.py").write_text("# user comment\ndef hello():\n    return 1\n")
        (self.repo / "unrelated.txt").write_text("keep this")
        self.runs = self.base / "runs"
        self.payload = dict(
            title="Return two",
            roots=[dict(alias="project", path=str(self.repo))],
            goal="Return 2 from hello.",
            criteria="hello returns 2; preserve unrelated content.",
            verification="Manually exercise the caller",
        )

    def test_markdown_has_structured_roots_and_verification(self):
        text, title = build_task(self.payload, self.runs)
        meta = json.loads(text.split("```countersign-task\n")[1].split("```")[0])
        self.assertEqual(meta["roots"], {"project": str(self.repo)})
        self.assertEqual(meta["verification"], ["Manually exercise the caller"])
        self.assertIn("# Return two", text)
        self.assertIn("## Acceptance criteria", text)
        self.assertEqual(title, "Return two")

    def test_title_criteria_and_alias_have_defaults(self):
        other = self.base / "other repo"
        other.mkdir()
        payload = dict(
            roots=[dict(alias="", path=str(self.repo)), dict(path=str(other))],
            goal="Return 2 from hello.\nKeep the docstring.",
        )
        text, title = build_task(payload, self.runs)
        meta = json.loads(text.split("```countersign-task\n")[1].split("```")[0])
        self.assertEqual(meta["roots"], {"repo": str(self.repo), "other-repo": str(other)})
        self.assertEqual(title, "Return 2 from hello.")
        self.assertIn("## Acceptance criteria\nThe Goal is achieved", text)
        long_goal = "word " * 40
        self.assertEqual(build_task(dict(payload, goal=long_goal), self.runs)[1][-3:], "...")
        clash = [dict(path=str(self.repo)), dict(alias="repo", path=str(other))]
        with self.assertRaisesRegex(ValueError, "unique"):
            build_task(dict(payload, roots=clash), self.runs)
        renamed = [dict(alias="repo", path=str(other)), dict(path=str(self.repo))]
        meta = json.loads(
            build_task(dict(payload, roots=renamed), self.runs)[0].split("```")[1][17:]
        )
        self.assertEqual(meta["roots"]["repo-2"], str(self.repo))

    def test_invalid_tasks_never_create_files(self):
        cases = [
            dict(goal=""),
            dict(roots=[dict(alias="bad alias", path=str(self.base / "repo"))]),
            dict(command=["sh"]),
            dict(roots=[dict(alias="project", path="/")]),
            dict(roots=[]),
            dict(roots=[dict(alias="project", path="relative")]),
            dict(roots=[dict(alias="project", path=str(self.base))]),
            dict(roots=[dict(alias="project", path=str(self.repo))] * 2),
            dict(goal="```countersign-task\n{}\n```"),
            dict(title="a\nb"),
        ]
        for change in cases:
            with self.subTest(change=change), self.assertRaises((ValueError, OSError)):
                build_task(dict(self.payload, **change), self.runs)
        self.assertFalse(self.runs.exists())

    def test_busy_server_does_not_launch_a_second_worker(self):
        launcher = TaskLauncher(self.runs)
        with patch("countersign.web.submissions.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            launcher.submit(self.payload)
            with self.assertRaises(BusyError):
                launcher.submit(self.payload)
            self.assertEqual(popen.call_count, 1)
            self.assertNotIn("shell", popen.call_args.kwargs)

    def start_server(self, settings=None):
        server = make_server(self.runs, 0, settings=settings)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(stop)
        url = f"http://127.0.0.1:{server.server_port}"
        with urlopen(url + "/api/session") as response:
            token = json.load(response)["token"]
        return url, {
            "Content-Type": "application/json",
            "Origin": url,
            "X-Countersign-Token": token,
        }

    def test_browser_submission_requires_same_origin_token_and_valid_payload(self):
        url, headers = self.start_server()
        for replacement, expected in [
            ({"X-Countersign-Token": ""}, 403),
            ({"Origin": "http://evil.example"}, 403),
            ({"Content-Type": "text/plain"}, 415),
        ]:
            with self.assertRaises(HTTPError) as error:
                urlopen(
                    Request(
                        url + "/api/tasks",
                        data=json.dumps(self.payload).encode(),
                        headers=dict(headers, **replacement),
                    )
                )
            self.assertEqual(error.exception.code, expected)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(url + "/api/tasks", data=b"{}", headers=headers))
        self.assertEqual(error.exception.code, 400)
        self.assertFalse(self.runs.exists())

    def test_http_creation_to_completed_run_uses_normal_workflow(self):
        settings = self.base / "settings.json"
        settings.write_text(
            json.dumps(
                dict(
                    command=[
                        sys.executable,
                        str(BASE / "tests/fake_live.py"),
                        "--profiles",
                        str(self.base / "profiles"),
                        "--mode",
                        "ok",
                    ],
                    agent_source=str(BASE / "countersign/agents"),
                    agent_directory=str(self.base / "profiles"),
                    timeout_seconds=5,
                )
            )
        )
        url, headers = self.start_server(settings)
        with urlopen(
            Request(url + "/api/tasks", data=json.dumps(self.payload).encode(), headers=headers)
        ) as response:
            self.assertEqual(response.status, 202)
            name = json.load(response)["id"]
        manifest = self.runs / ".submissions" / name / "launch.json"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = json.loads(manifest.read_text())
            if state["status"] not in ("STARTING", "RUNNING"):
                break
            time.sleep(0.05)
        self.assertEqual(
            state["status"], "READY_FOR_REVIEW", (manifest.parent / "console.log").read_text()
        )
        with urlopen(url + "/api/run?id=" + name) as response:
            result = json.load(response)
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        self.assertEqual(
            [stage["stage"] for stage in result["stages"]],
            ["planner", "plan-reviewer", "implementer", "check", "reviewer"],
        )
        self.assertIn("return 2", (self.repo / "hello.py").read_text())
        self.assertEqual((self.repo / "unrelated.txt").read_text(), "keep this")

    def test_restart_and_resume_actions_use_worker_and_preserve_history(self):
        run = self.runs / "existing-run"
        (run / "00-input").mkdir(parents=True)
        text, _ = build_task(self.payload, self.runs)
        (run / "00-input/task.md").write_text(text)
        (run / "run.json").write_text(
            json.dumps(
                dict(
                    status="TIMEOUT",
                    contract_version=1,
                    roots={"project": str(self.repo)},
                    stages=[],
                )
            )
        )
        (run / "checkpoint.json").write_text("{}")
        url, headers = self.start_server()
        with patch("countersign.web.submissions.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = 0
            with urlopen(
                Request(
                    url + "/api/actions",
                    data=json.dumps(dict(id=run.name, action="restart")).encode(),
                    headers=headers,
                )
            ) as response:
                restarted = json.load(response)
            self.assertEqual(restarted["id"], run.name)
            self.assertEqual(restarted["draft"]["goal"], self.payload["goal"])
            popen.assert_not_called()
            with urlopen(
                Request(
                    url + "/api/actions",
                    data=json.dumps(dict(id=run.name, action="resume")).encode(),
                    headers=headers,
                )
            ) as response:
                resumed = json.load(response)
            self.assertEqual(resumed["id"], run.name)
            self.assertIn("--resume", popen.call_args.args[0])
            self.assertEqual(json.loads((run / "run.json").read_text())["status"], "TIMEOUT")
            self.assertEqual(
                (self.repo / "hello.py").read_text(), "# user comment\ndef hello():\n    return 1\n"
            )
        with self.assertRaises(HTTPError) as error:
            urlopen(
                Request(
                    url + "/api/actions",
                    data=json.dumps(dict(id=run.name, action="resume")).encode(),
                    headers=dict(headers, **{"X-Countersign-Token": ""}),
                )
            )
        self.assertEqual(error.exception.code, 403)


class ApprovalHttpTests(unittest.TestCase):
    setUp = SubmissionTests.setUp
    start_server = SubmissionTests.start_server

    def test_decision_endpoint_requires_auth_and_exact_ticket(self):
        run = self.runs / "approval"
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps(dict(status="RUNNING", stages=[], roots={})))
        (run / "00-input").mkdir()
        (run / "00-input/task.md").write_text("# Approval task\nInspect Python version")
        pending = dict(ticket="exact-ticket", request=dict(argv=["python3", "--version"]))
        (run / "pending-approval.json").write_text(json.dumps(pending))
        url, headers = self.start_server()
        payload = dict(id=run.name, ticket="exact-ticket", decision="deny", alternative="")
        for body, extra, code in [
            (payload, {"X-Countersign-Token": ""}, 403),
            (payload, {"Origin": "http://untrusted.example"}, 403),
            (dict(payload, ticket="stale"), {}, 400),
            ([], {}, 400),
        ]:
            with self.subTest(body=body, extra=extra), self.assertRaises(HTTPError) as failure:
                urlopen(
                    Request(
                        url + "/api/decision",
                        data=json.dumps(body).encode(),
                        headers=dict(headers, **extra),
                    )
                )
            self.assertEqual(failure.exception.code, code)
        self.assertFalse((run / "approval-decision.json").exists())
        with urlopen(
            Request(url + "/api/decision", data=json.dumps(payload).encode(), headers=headers)
        ) as response:
            self.assertEqual(response.status, 202)
        self.assertEqual(json.loads((run / "approval-decision.json").read_text()), payload)
        with urlopen(url + "/api/run?id=approval") as response:
            self.assertEqual(json.load(response)["pending_approval"], pending)
