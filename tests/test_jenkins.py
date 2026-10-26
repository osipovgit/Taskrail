"""Jenkins through the executor: config, schema, HTTP flows and stage routing."""

import base64
import copy
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch
from urllib.parse import parse_qs

from taskrail.application import execution_wait, jenkins_requests
from taskrail.executor import (
    client,
    jenkins_build,
    jenkins_config,
    jenkins_reads,
    jenkins_schema,
    worker,
)
from taskrail.executor.service import ExecutorServer
from taskrail.executor.store import TicketStore
from taskrail.interactions import jenkins

EXAMPLE = Path(__file__).resolve().parents[1] / "deploy/executor-jenkins.example.json"
READ = dict(
    server="ci",
    job="shop-tests",
    operation="status",
    build="last",
    parameters={},
    reason="Check the latest test run",
    timeout_seconds=60,
)
BUILD = dict(READ, operation="build", build="new", parameters={"BRANCH": "main"})


class FakeJenkins(BaseHTTPRequestHandler):
    """Answers like Jenkins for one job; records every request."""

    log: ClassVar[list] = []
    queue_polls = 0
    build_polls = 0

    def log_message(self, *args):
        """Quiet."""

    def reply(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def document(self, value):
        self.reply(200, json.dumps(value).encode())

    def do_GET(self):
        FakeJenkins.log.append(("GET", self.path, self.headers.get("Authorization")))
        job = "/job/shop/job/tests"
        path = self.path.split("?")[0]
        if path == job + "/lastBuild/api/json":
            return self.document(dict(number=7, result="SUCCESS", building=False))
        if path == job + "/7/consoleText":
            return self.reply(200, b"x" * 100000 + b"DONE\n")
        if path in {job + "/7/testReport/api/json", job + "/8/testReport/api/json"}:
            cases = [
                dict(className="a", name="ok", status="PASSED"),
                dict(className="a", name="broken", status="FAILED"),
            ]
            return self.document(
                dict(passCount=1, failCount=1, skipCount=0, suites=[dict(cases=cases)])
            )
        if path == job + "/9/api/json":
            return self.reply(302, headers=[("Location", "http://198.51.100.1/steal")])
        if path == "/queue/item/42/api/json":
            FakeJenkins.queue_polls += 1
            number = 8 if FakeJenkins.queue_polls > 1 else None
            return self.document(dict(executable=number and dict(number=number)))
        if path == job + "/8/api/json":
            FakeJenkins.build_polls += 1
            running = FakeJenkins.build_polls < 2
            return self.document(
                dict(number=8, building=running, result=None if running else "FAILURE")
            )
        if path == job + "/8/consoleText":
            return self.reply(200, b"tests failed\n")
        return self.reply(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode())
        FakeJenkins.log.append(("POST", self.path, self.headers.get("Authorization"), form))
        if self.path == "/job/shop/job/tests/buildWithParameters":
            return self.reply(201, headers=[("Location", "http://jenkins.invalid/queue/item/42/")])
        return self.reply(404)


class JenkinsTest(unittest.TestCase):
    def setUp(self):
        FakeJenkins.log = []
        FakeJenkins.queue_polls = 0
        FakeJenkins.build_polls = 0
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), FakeJenkins)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.servers = json.loads(EXAMPLE.read_text())
        self.servers["ci"]["url"] = f"http://127.0.0.1:{self.http.server_port}"
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_example_configuration_is_valid_and_tokens_stay_private(self):
        path = self.root / "jenkins.json"
        path.write_text(EXAMPLE.read_text())
        servers = jenkins_config.load(path)
        self.assertNotIn("token", json.dumps(jenkins_config.public(servers)))
        self.assertEqual(jenkins_config.load(self.root / "missing.json"), {})

    def test_configuration_rejects_unsafe_values(self):
        for change in (
            dict(url="https://user:secret@jenkins.example.com"),
            dict(url="file:///etc/passwd"),
            dict(extra=True),
            dict(jobs={}),
            dict(jobs={"x": dict(path="a/../b", parameters=[])}),
            dict(jobs={"x": dict(path="a", parameters=["--flag"])}),
            dict(ca_file="/tmp/ca.pem"),
        ):
            server = dict(self.servers["ci"], **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                jenkins_config.check_server(server)

    def test_requests_use_only_configured_jobs_and_parameters(self):
        self.assertEqual(jenkins_schema.validate(copy.deepcopy(READ), self.servers), READ)
        jenkins_schema.validate(copy.deepcopy(BUILD), self.servers)
        for change in (
            dict(job="unknown"),
            dict(operation="delete"),
            dict(build=True),
            dict(build=0),
            dict(parameters={"BRANCH": "main"}),
            dict(operation="build", build="last"),
            dict(operation="build", build="new", parameters={"TOKEN": "x"}),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                jenkins_schema.validate(dict(READ, **change), self.servers)

    def test_reads_status_console_tail_and_failed_tests(self):
        status = jenkins_reads.read(self.servers, READ)
        self.assertEqual(status["build"]["number"], 7)
        account = base64.b64encode(b"taskrail-bot:REPLACE_WITH_JENKINS_API_TOKEN").decode()
        self.assertEqual(FakeJenkins.log[0][2], "Basic " + account)
        console = jenkins_reads.read(self.servers, dict(READ, operation="console", build=7))
        self.assertTrue(console["truncated"])
        self.assertTrue(console["console"].endswith("DONE\n"))
        report = jenkins_reads.read(self.servers, dict(READ, operation="tests"))
        self.assertEqual([case["name"] for case in report["tests"]["failed_cases"]], ["broken"])
        missing = jenkins_reads.read(self.servers, dict(READ, build=5))
        self.assertEqual((missing["status"], missing["http_status"]), ("FAILED", 404))

    def test_redirects_are_refused_so_the_token_stays_on_the_server(self):
        outcome = jenkins_reads.read(self.servers, dict(READ, build=9))
        self.assertEqual((outcome["status"], outcome["http_status"]), ("FAILED", 302))
        self.assertEqual(len(FakeJenkins.log), 1)

    def test_build_waits_for_queue_and_result_without_retrying(self):
        with patch.object(jenkins_build, "POLL_SECONDS", 0):
            outcome = jenkins_build.perform(self.servers, BUILD)
        self.assertEqual(outcome["status"], "FAILED")
        self.assertEqual(outcome["build"]["result"], "FAILURE")
        self.assertIn("tests failed", outcome["console"])
        self.assertEqual(outcome["tests_status"], "available")
        self.assertEqual(outcome["tests"]["failCount"], 1)
        self.assertTrue(any("/8/testReport/" in entry[1] for entry in FakeJenkins.log))
        self.assertFalse(any("/lastBuild/" in entry[1] for entry in FakeJenkins.log))
        posts = [entry for entry in FakeJenkins.log if entry[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][3], {"BRANCH": ["main"]})
        queue = [entry for entry in FakeJenkins.log if "/queue/item/42/" in entry[1]]
        self.assertTrue(all(entry[1].startswith("/queue") for entry in queue))

    def test_build_timeout_and_refusal_are_reported(self):
        with patch.object(jenkins_build, "POLL_SECONDS", 0):
            refused = jenkins_build.perform(
                self.servers, dict(BUILD, job="shop-deploy-staging", parameters={})
            )
        self.assertEqual(refused["status"], "FAILED")
        self.assertIn("HTTP 404", refused["detail"])
        queued = dict(BUILD, timeout_seconds=1)
        with patch.object(jenkins_build.time, "monotonic", side_effect=[0, 0, 5, 5]):
            self.assertEqual(jenkins_build.perform(self.servers, queued)["status"], "UNKNOWN")

    def test_executor_reads_directly_but_builds_need_a_root_ticket(self):
        store = TicketStore(self.root / "tickets")
        server = object.__new__(ExecutorServer)
        server.client_uid = 1000
        self.servers["ci"]["jobs"]["shop-tests"]["approval"] = "root"
        server.configs = {"ssh": {}, "jenkins": self.servers}
        server.store = store
        catalog = server.dispatch(dict(operation="catalog"), 1000)
        self.assertNotIn("token", json.dumps(catalog))
        read = server.dispatch(dict(operation="jenkins-read", request=READ), 1000)
        self.assertEqual(read["status"], "SUCCEEDED")
        with self.assertRaisesRegex(ValueError, "root-approved"):
            server.dispatch(dict(operation="jenkins-read", request=BUILD), 1000)
        ticket = server.dispatch(dict(operation="submit", key="k1", jenkins=BUILD), 1000)
        self.assertEqual((ticket["kind"], ticket["status"]), ("jenkins", "PENDING_APPROVAL"))
        approval = dict(operation="approve", id=ticket["id"], digest=ticket["digest"])
        with self.assertRaises(ValueError):
            server.dispatch(approval, 1000)
        with patch.object(threading.Thread, "start") as start:
            self.assertEqual(server.dispatch(approval, 0)["status"], "RUNNING")
        self.assertEqual(start.call_count, 1)
        outcome = dict(status="SUCCEEDED", build=dict(number=8))
        with patch.object(jenkins_build, "perform", return_value=outcome) as perform:
            worker.perform(store, store.get(ticket["id"]), self.servers)
        perform.assert_called_once_with(self.servers, BUILD)
        self.assertEqual(store.get(ticket["id"])["status"], "SUCCEEDED")

    def test_a_job_root_preapproved_in_the_configuration_builds_without_a_ticket_wait(self):
        servers = copy.deepcopy(self.servers)
        self.assertEqual(servers["ci"]["jobs"]["shop-tests"]["approval"], "none")
        jenkins_config.check_server(servers["ci"])
        server = object.__new__(ExecutorServer)
        server.client_uid = 1000
        server.configs = {"ssh": {}, "jenkins": servers}
        server.store = TicketStore(self.root / "tickets")
        with patch.object(threading.Thread, "start") as start:
            started = server.dispatch(dict(operation="submit", key="k1", jenkins=BUILD), 1000)
            repeated = server.dispatch(dict(operation="submit", key="k1", jenkins=BUILD), 1000)
        self.assertEqual(started["status"], "RUNNING")
        self.assertEqual(start.call_count, 1)
        self.assertEqual(repeated["status"], "RUNNING")
        catalog = server.dispatch(dict(operation="catalog"), 1000)
        self.assertEqual(catalog["jenkins"]["ci"]["jobs"]["shop-tests"]["approval"], "none")
        deploy = dict(BUILD, job="shop-deploy-staging", parameters={"VERSION": "1"})
        ticket = server.dispatch(dict(operation="submit", key="k2", jenkins=deploy), 1000)
        self.assertEqual(ticket["status"], "PENDING_APPROVAL")
        servers["ci"]["jobs"]["shop-tests"]["approval"] = "always"
        with self.assertRaisesRegex(ValueError, "root"):
            jenkins_config.check_server(servers["ci"])

    def test_stage_reads_need_ui_approval_and_builds_become_tickets(self):
        run = self.root / "run"
        folder = run / "01-plan"
        folder.mkdir(parents=True)
        decisions = []
        actions = SimpleNamespace(run=run, folder=folder)
        actions.approve = lambda request: decisions.append(request) or dict(decision="allow")
        envelope = dict(schema_version=1, status="JENKINS_REQUEST", jenkins=READ)
        answers = [
            dict(jenkins=jenkins_config.public(self.servers)),
            dict(status="SUCCEEDED", build={}),
        ]
        with patch.object(client, "request", side_effect=answers) as request:
            response = jenkins.consume(actions, json.dumps(envelope))
        self.assertEqual(decisions[0]["jenkins"], READ)
        self.assertEqual(request.call_args.args[0]["operation"], "jenkins-read")
        self.assertIn("00-input/local", response)
        self.assertIsNone(jenkins.consume(actions, '{"status": "PLAN_READY"}'))
        bad = dict(envelope, jenkins=dict(READ, job="unknown"))
        with patch.object(client, "request", return_value=answers[0]):
            self.assertIn("rejected", jenkins.consume(actions, json.dumps(bad)))
        session = SimpleNamespace(environment=dict(run=run), active=(folder,), state={})
        actions.session = session
        envelope["jenkins"] = BUILD
        with (
            patch.object(client, "request", return_value=answers[0]),
            patch.object(execution_wait, "resume", return_value="built") as resume,
            patch("taskrail.interactions.jenkins.ApprovalPause"),
        ):
            self.assertEqual(jenkins.consume(actions, json.dumps(envelope)), "built")
        resume.assert_called_once()
        self.assertEqual(execution_wait.read(run)[0]["request"]["jenkins"], BUILD)

    def test_instructions_appear_only_when_jenkins_is_configured(self):
        self.assertEqual(jenkins_requests.instructions({}), "")
        text = jenkins_requests.instructions(jenkins_config.public(self.servers))
        self.assertIn("JENKINS_REQUEST", text)
        self.assertIn("shop-tests", text)
        self.assertNotIn("REPLACE_WITH_JENKINS_API_TOKEN", text)
