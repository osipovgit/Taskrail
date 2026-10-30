import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from taskrail.web.run_messages import public_messages
from taskrail.web.server import make_server


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "runs"
        self.run = self.base / "example"
        (self.run / "00-input").mkdir(parents=True)
        (self.run / "01-plan").mkdir()
        (self.run / "00-input/task.md").write_text("# Example task\nKeep existing work")
        self.index = self.run / "run.json"
        self.index.write_text(
            json.dumps(
                dict(
                    status="RUNNING",
                    stages=[dict(number=1, stage="planner", directory="01-plan", status="RUNNING")],
                    roots={},
                )
            )
        )
        self.events = self.run / "01-plan/events.jsonl"
        self.events.write_text(
            json.dumps(dict(type="text", part=dict(id="one", text="Reading files"))) + '\n{"type":'
        )
        self.server = make_server(self.base, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get(self, path, **kwargs):
        with urlopen(Request(self.url + path, **kwargs), timeout=2) as response:
            return response.read().decode()

    def test_live_index_messages_and_completed_result(self):
        self.assertEqual(json.loads(self.get("/api/runs"))[0]["title"], "Example task")
        value = json.loads(self.get("/api/run?id=example"))
        self.assertEqual(value["stages"][0]["messages"]["items"][0]["text"], "Reading files")
        self.assertIsNone(value["stages"][0]["result"])
        result = dict(
            status="PLAN_READY", summary="<script>alert(1)</script>", proposed_change_files=[]
        )
        (self.run / "01-plan/result.json").write_text(json.dumps(result))
        self.assertEqual(json.loads(self.get("/api/run?id=example"))["stages"][0]["result"], result)
        self.assertIn("/dashboard.js", self.get("/"))
        self.assertIn("/dashboard.css", self.get("/"))
        self.assertIn(".stage-meta", self.get("/dashboard.css"))
        self.assertIn('rel="icon" href="/favicon.svg"', self.get("/"))
        self.assertIn("<svg", self.get("/favicon.svg"))
        self.assertIn("./modules/app.js", self.get("/dashboard.js"))
        self.assertIn("textContent", self.get("/modules/dom.js"))
        self.assertIn("showAnalytics", self.get("/modules/analytics.js"))
        self.assertIn("taskSection", self.get("/modules/task.js"))
        # Every dashboard module is served; a module missing from the list breaks the page.
        static = Path(__file__).resolve().parents[1] / "taskrail/web/static/modules"
        for module in sorted(static.glob("*.js")):
            with self.subTest(module=module.name):
                self.assertIn("export", self.get(f"/modules/{module.name}"))
        totals = json.loads(self.get("/api/analytics"))
        self.assertEqual(totals["runs"]["count"], 1)
        self.assertEqual(totals["stages"]["planner"]["attempts"], 1)

    def test_messages_ignore_reasoning_tools_and_incomplete_lines(self):
        events = [
            dict(type="reasoning", part=dict(text="not public")),
            dict(type="tool_use", part=dict(text="not a chat message")),
            dict(type="text", part=dict(id="one", text="public")),
            dict(type="text", part=dict(id="one", text="public")),
        ]
        self.events.write_text("\n".join(json.dumps(e) for e in events) + "\n{")
        self.assertEqual(
            public_messages(self.events)["items"], [{"text": "public", "timestamp": None}]
        )

    def test_display_resolves_aliases_and_keeps_source_events_unchanged(self):
        state = json.loads(self.index.read_text())
        state["roots"] = {"qa": "/actual/project"}
        state["changed_files"] = ["qa/file.py"]
        self.index.write_text(json.dumps(state))
        raw = json.dumps(
            dict(
                type="text",
                timestamp=1791790000000,
                part=dict(id="absolute", text="Read qa/file.py"),
            )
        )
        self.events.write_text(raw + "\n")
        (self.run / "01-plan/result.json").write_text(
            json.dumps(dict(summary="Read qa/file.py", files_read=["qa/file.py"]))
        )
        value = json.loads(self.get("/api/run?id=example"))
        stage = value["stages"][0]
        self.assertEqual(stage["result"]["files_read"], ["/actual/project/file.py"])
        self.assertEqual(
            stage["messages"]["items"][0],
            dict(text="Read /actual/project/file.py", timestamp=1791790000000),
        )
        self.assertEqual(value["changed_files"], ["/actual/project/file.py"])
        self.assertEqual(self.events.read_text(), raw + "\n")

    def test_traversal_symlinks_and_unrelated_files_not_exposed(self):
        (self.base / "escape").symlink_to(self.base.parent, target_is_directory=True)
        for path in [
            "/api/run?id=..",
            "/api/run?id=..%2Fsecret",
            "/api/run?id=escape",
            "/etc/passwd",
        ]:
            with self.assertRaises(HTTPError) as error:
                self.get(path)
            with error.exception as response:
                self.assertEqual(response.code, 404)

    def test_mutations_and_foreign_origins_rejected(self):
        original = self.index.read_bytes()
        for kwargs, expected in [
            ({"method": "POST", "data": b"{}"}, 403),
            ({"headers": {"Host": "attacker.example"}}, 403),
            ({"headers": {"Host": "attacker.example:9000"}}, 403),
            ({"headers": {"Host": "localhost"}}, 403),
            ({"headers": {"Host": "localhost:9000", "Origin": "http://localhost:8787"}}, 403),
            ({"headers": {"Origin": "https://attacker.example"}}, 403),
        ]:
            with self.assertRaises(HTTPError) as error:
                self.get("/api/run?id=example", **kwargs)
            with error.exception as response:
                self.assertEqual(response.code, expected)
        self.assertEqual(self.index.read_bytes(), original)

    def test_ssh_tunnel_on_another_local_port_is_trusted(self):
        page = self.get("/api/runs", headers={"Host": "localhost:9000"})
        self.assertEqual(json.loads(page)[0]["title"], "Example task")

    def test_corrupt_index_does_not_break_run_list(self):
        self.index.write_text("{")
        listed = json.loads(self.get("/api/runs"))
        self.assertEqual(listed[0]["id"], "example")
        self.assertEqual(listed[0]["status"], "RECOVERY_REQUIRED")
        self.assertEqual(listed[0]["group"], "attention")
        detail = json.loads(self.get("/api/run?id=example"))
        self.assertEqual(detail["status"], "RECOVERY_REQUIRED")
        self.assertEqual(detail["actions"], {})
        self.assertEqual(self.index.read_text(), "{")
