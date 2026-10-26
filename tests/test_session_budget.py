"""Session context headroom is independent of cumulative provider token usage."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from countersign.application import context_windows, session_budget
from countersign.application.attempt_retries import Retries
from countersign.application.attempt_session import launch_options
from countersign.application.live import execute_task
from countersign.application.task_config import limits
from countersign.infrastructure import usage_limits
from countersign.infrastructure.runner import run_agent
from countersign.observability.telemetry import Telemetry


def usage(identity, incoming, cached=0, total=1):
    return dict(
        type="step_finish",
        sessionID="session",
        part=dict(
            id=identity,
            tokens=dict(input=incoming, cache=dict(read=cached, write=0), total=total),
        ),
    )


class SessionBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_positive_headroom_and_conservative_defaults(self):
        configured = limits({})
        self.assertEqual(configured["model_context_tokens"], 94208)
        self.assertEqual(configured["context_reserve_tokens"], 8192)
        self.assertEqual(context_windows.capacity(configured), 86016)
        for context, reserve in ((0, 1), (10, 0), (10, 10), (10, 11)):
            with (
                self.subTest(context=context, reserve=reserve),
                self.assertRaisesRegex(ValueError, "context_reserve_tokens"),
            ):
                context_windows.settings(
                    dict(model_context_tokens=context, context_reserve_tokens=reserve)
                )

    def test_each_model_gets_its_own_window_and_unlisted_models_the_default(self):
        windows = {"lab/small": 32768, "lab/large": 200000, "default": 65536}
        config = limits(dict(model_context_tokens=windows))
        self.assertEqual(context_windows.capacity(config, "lab/small"), 32768 - 8192)
        self.assertEqual(context_windows.capacity(config, "lab/large"), 200000 - 8192)
        self.assertEqual(context_windows.capacity(config, "lab/other"), 65536 - 8192)
        self.assertEqual(context_windows.capacity(config, None), 65536 - 8192)
        listed_only = limits(dict(model_context_tokens={"lab/small": 32768}))
        self.assertEqual(context_windows.capacity(listed_only, "lab/other"), 94208 - 8192)
        for invalid in ({}, {"lab/small": 4096}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                limits(dict(model_context_tokens=invalid))

    def test_admission_uses_the_window_of_the_role_model(self):
        (self.root / "agent.md").write_text("Read-only role")
        (self.root / "request.md").write_text("x" * 30000)
        windows = {"lab/small": 20000, "lab/large": 200000}
        config = dict(model_context_tokens=windows, models={"planner": "lab/small"})
        record = dict(role="planner")
        self.assertEqual(
            session_budget.admission(config, (self.root, record), [])["status"],
            "CONTEXT_EXCEEDED",
        )
        self.assertEqual(record["context_budget"]["input_capacity_tokens"], 20000 - 8192)
        config["models"]["planner"] = "lab/large"
        self.assertIsNone(session_budget.admission(config, (self.root, record), []))

    def test_writer_admission_counts_frozen_role_and_distinct_planned_bytes(self):
        (self.root / "request.md").write_text("request")
        (self.root / "agent.md").write_text("frozen role")
        source = self.root / "source.py"
        source.write_text("\u0430" * 50000, encoding="utf-8")
        record = dict(role="implementer")
        outcome = session_budget.admission(
            {}, (self.root, record), [source, source, self.root / "new.py"]
        )
        self.assertEqual(outcome["status"], "CONTEXT_EXCEEDED")
        self.assertIn("Split this task", outcome["errors"][0])
        measured = record["context_budget"]
        self.assertEqual(measured["planned_input_bytes"], 100000)
        self.assertEqual(measured["estimated_input_tokens"], 100018 + 1024)
        self.assertEqual(measured["bytes_per_token"], 1)
        source.write_text("small")
        self.assertIsNone(session_budget.admission({}, (self.root, record), [source]))

    def test_nonwriter_admission_does_not_need_planned_sources(self):
        (self.root / "agent.md").write_text("Read-only role")
        (self.root / "request.md").write_text("Small request")
        for role in ("planner", "reviewer"):
            with self.subTest(role=role):
                self.assertIsNone(session_budget.admission({}, (self.root, dict(role=role)), []))

    def test_permission_frontmatter_does_not_consume_model_context(self):
        (self.root / "request.md").write_text("request")
        permissions = json.dumps(dict(permission=dict(read={"/" + "x" * 50000: "allow"})))
        (self.root / "agent.md").write_text(f"---\n{permissions}\n---\nfrozen role\n")
        record = dict(role="implementer")
        self.assertIsNone(session_budget.admission({}, (self.root, record), []))
        self.assertEqual(record["context_budget"]["role_bytes"], len("frozen role\n"))

    def test_plan_inputs_include_read_dependencies_and_new_edit_targets(self):
        existing = self.root / "existing.py"
        existing.write_text("source")
        plan = dict(
            files_read=["repo/existing.py"],
            proposed_change_files=["repo/existing.py", "repo/new.py"],
        )
        self.assertEqual(
            session_budget.plan_inputs(plan, dict(repo=self.root)),
            [existing, self.root / "new.py"],
        )
        self.assertEqual(session_budget.plan_inputs(None, {}), [])
        plan["files_read"] = ["repo/../outside.py"]
        with self.assertRaisesRegex(ValueError, "Noncanonical"):
            session_budget.plan_inputs(plan, dict(repo=self.root))

    def test_review_does_not_validate_files_removed_by_the_implementer(self):
        plan = dict(files_read=["repo/deleted.py"], proposed_change_files=["repo/deleted.py"])
        for role in ("planner", "reviewer"):
            with self.subTest(role=role):
                self.assertEqual(session_budget.plan_inputs(plan, dict(repo=self.root), role), [])

    def test_repair_admission_accepts_only_approved_deleted_inputs(self):
        plan = dict(files_read=["repo/deleted.py"], proposed_change_files=["repo/deleted.py"])
        self.assertEqual(
            session_budget.plan_inputs(plan, dict(repo=self.root)), [self.root / "deleted.py"]
        )
        plan["files_read"].append("repo/missing-dependency.py")
        with self.assertRaisesRegex(ValueError, "absent"):
            session_budget.plan_inputs(plan, dict(repo=self.root))

    def test_every_role_disables_compaction_and_receives_context_headroom(self):
        workflow = SimpleNamespace(
            run=self.root,
            config=dict(
                command=["opencode"], roots=dict(repo=self.root), models={}, agent_env_allow=[]
            ),
            runtime=dict(debug=False, profile_suffix="test"),
        )
        for role in ("planner", "implementer", "reviewer"):
            for format_only in (False, True):
                with self.subTest(role=role, format_only=format_only):
                    files = [str(self.root / "source.py")]
                    active = (self.root, dict(role=role, stage=role, writable_files=files))
                    launch = launch_options(workflow, active, 100000, format_only)
                    self.assertIs(launch["runtime"]["autocompact"], False)
                    self.assertEqual(launch["runtime"]["context_budget"], 86016)
                    self.assertEqual(launch["runtime"]["token_budget"], 100000)
                    plan_file = str(self.root / "plan.md")
                    expected = plan_file if role == "planner" and not format_only else None
                    self.assertEqual(launch["runtime"]["plan_file"], expected)
                    writable = files if role == "implementer" and not format_only else ()
                    self.assertEqual(launch["runtime"]["writable_files"], writable)

    def test_context_uses_latest_input_and_both_cache_categories(self):
        telemetry = Telemetry()
        telemetry.observe(json.dumps(usage("first", 600, total=2000)))
        telemetry.observe(json.dumps(usage("second", 700, total=2000)))
        self.assertEqual(usage_limits.exceeded(telemetry, None, 1000), "OK")
        self.assertEqual(usage_limits.exceeded(telemetry, 4000, 1000), "TOKEN_BUDGET_EXCEEDED")
        latest = usage("third", 700, cached=200)
        latest["part"]["tokens"]["cache"]["write"] = 100
        telemetry.observe(json.dumps(latest))
        self.assertEqual(telemetry.summary()["last_input"], 1000)
        self.assertEqual(usage_limits.exceeded(telemetry, None, 1000), "CONTEXT_EXCEEDED")

    def test_unreported_usage_does_not_claim_zero_input(self):
        telemetry = Telemetry()
        telemetry.observe(json.dumps(dict(type="step_finish", part=dict(id="unknown"))))
        self.assertIsNone(telemetry.summary()["last_input"])
        self.assertEqual(usage_limits.exceeded(telemetry, None, 1000), "OK")

    def test_compaction_markers_stop_even_without_provider_usage(self):
        for event in (
            dict(type="session.compacted"),
            dict(type="compaction"),
            dict(type="message.part.updated", part=dict(type="compaction")),
        ):
            with self.subTest(event=event):
                telemetry = Telemetry()
                telemetry.observe(json.dumps(event))
                self.assertEqual(usage_limits.exceeded(telemetry, None), "CONTEXT_EXCEEDED")

    def test_runtime_stops_before_reserve_is_spent(self):
        outcome = self.run_script(usage("occupied", 700, cached=300), pause=True)
        self.assertEqual(outcome["status"], "CONTEXT_EXCEEDED")
        self.assertIn("1000 reported input tokens", outcome["errors"][0])
        self.assertLess(outcome["elapsed_seconds"], 5)

    def test_final_partial_event_is_checked_after_clean_exit(self):
        for index, event in enumerate(
            (usage("occupied", 700, cached=300), dict(type="session.compacted"))
        ):
            with self.subTest(event=event):
                outcome = self.run_script(event, name=f"drain-{index}")
                self.assertEqual(outcome["status"], "CONTEXT_EXCEEDED")
                self.assertEqual(outcome["exit_code"], 0)

    def test_continuation_over_boundary_never_spawns_another_process(self):
        attempt = self.root / "continued"
        attempt.mkdir()
        attempt.joinpath("request.md").write_text("Initial request")
        attempt.joinpath("events.jsonl").write_text(json.dumps(usage("prior", 1000)) + "\n")
        followup = attempt / "tool-result.md"
        followup.write_text("Executor result")
        with patch("countersign.infrastructure.process_watch.subprocess.Popen") as launch:
            outcome = run_agent(
                dict(
                    command=["unused"],
                    workspace=self.root,
                    agent="test",
                    model="test",
                    prompt=followup,
                    attempt=attempt,
                    timeout=20,
                    runtime=dict(session_id="session", context_budget=1000),
                )
            )
        launch.assert_not_called()
        self.assertEqual(outcome["status"], "CONTEXT_EXCEEDED")

    def test_writer_context_failure_cannot_schedule_transport_retry(self):
        workflow = SimpleNamespace(
            flow=dict(stage="implementer"), state=dict(stages=[]), config=dict(read_retries=3)
        )
        retries = Retries(SimpleNamespace(workflow=workflow))
        with patch("countersign.application.attempt_retries.overflow_outputs", return_value=""):
            self.assertFalse(retries.allowed(dict(status="CONTEXT_EXCEEDED")))

    def test_workflow_refuses_oversized_initial_stage_without_retry_or_edits(self):
        project = self.root / "repo"
        project.mkdir()
        project.joinpath(".git").mkdir()
        project.joinpath(".git/HEAD").write_text("ref: refs/heads/main\n")
        source = project / "hello.py"
        original = "def hello():\n    return 1\n"
        source.write_text(original)
        task = self.root / "task.md"
        header = json.dumps(dict(roots=dict(project=str(project))))
        task.write_text(f"```countersign-task\n{header}\n```\nReturn 2")
        settings = self.root / "settings.json"
        settings.write_text(json.dumps(self.workflow_settings()))
        run, status = execute_task(task, settings, run_dir=self.root / "result")
        state = json.loads(run.joinpath("run.json").read_text())
        self.assertEqual(status, "CONTEXT_EXCEEDED", state.get("summary"))
        self.assertEqual(source.read_text(), original)
        self.assertEqual(len(state["stages"]), 1)
        rejected = state["stages"][0]
        self.assertEqual(rejected["role"], "planner")
        self.assertEqual(rejected["status"], "CONTEXT_EXCEEDED")
        self.assertEqual(rejected["elapsed_seconds"], 0)
        self.assertIn("Planner admission", state["summary"])
        self.assertEqual(run.joinpath(rejected["directory"], "events.jsonl").read_bytes(), b"")
        self.assertFalse(run.joinpath(rejected["directory"], "stderr.log").exists())

    def workflow_settings(self):
        base = Path(__file__).resolve().parents[1]
        profiles = self.root / "profiles"
        return dict(
            command=[
                sys.executable,
                str(base / "tests/fake_live.py"),
                "--profiles",
                str(profiles),
                "--mode",
                "ok",
            ],
            agent_source=str(base / "countersign/agents"),
            agent_directory=str(profiles),
            timeout_seconds=5,
            model_context_tokens=15000,
            context_reserve_tokens=5000,
        )

    def run_script(self, event, pause=False, name="attempt"):
        script = self.root / f"{name}.py"
        ending = "\n" if pause else ""
        script.write_text(
            "import sys, time\n"
            f"sys.stdout.write({json.dumps(event) + ending!r})\n"
            "sys.stdout.flush()\n" + ("time.sleep(10)\n" if pause else "")
        )
        prompt = self.root / "task.md"
        prompt.write_text("Test")
        return run_agent(
            dict(
                command=[sys.executable, str(script)],
                workspace=self.root,
                agent="test",
                model="test",
                prompt=prompt,
                attempt=self.root / name,
                timeout=20,
                runtime=dict(context_budget=1000),
            )
        )
