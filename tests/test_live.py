import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from countersign.application.live import execute_task
from countersign.application.plan_validation import canonical_plan, validate_plan
from countersign.application.planned_paths import safe_file
from countersign.application.task_config import configuration
from countersign.core.paths import tool_paths
from countersign.infrastructure.runner import run_agent as real_run_agent

BASE = Path(__file__).resolve().parents[1]


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        (self.root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.root / "hello.py").write_text("# user comment\ndef hello():\n    return 1\n")
        (self.root / "unrelated.txt").write_text("user dirty work\n")
        self.task = self.base / "task.md"
        self.task.write_text(
            "```countersign-task\n"
            + json.dumps({"roots": {"project": str(self.root)}})
            + "\n```\nReturn 2"
        )
        self.settings = self.base / "settings.json"
        self.profiles = self.base / "profiles"

    def run_mode(self, mode="ok", **overrides):
        settings = dict(
            command=[
                sys.executable,
                str(BASE / "tests/fake_live.py"),
                "--profiles",
                str(self.profiles),
                "--mode",
                mode,
            ],
            agent_source=str(getattr(self, "source", BASE / "countersign/agents")),
            agent_directory=str(self.profiles),
            timeout_seconds=1
            if mode
            in (
                "writer-timeout",
                "timeout-then-invalid",
                "timeout-evidence",
                "review-timeout",
                "planner-timeout",
            )
            else 5,
        )
        settings.update(overrides)
        self.settings.write_text(json.dumps(settings))
        with patch(
            "countersign.interactions.approvals.wait",
            return_value=dict(decision="deny", alternative="Use permitted source paths"),
        ):
            run, status = execute_task(self.task, self.settings, run_dir=self.base / "result")
        state = json.loads((run / "run.json").read_text())
        return run, status, state

    def test_git_history_and_revert_complete_the_workflow(self):
        from countersign.git import process

        process.checked(self.root, ["init", "-b", "main"])
        process.checked(self.root, ["config", "user.name", "Fixture"])
        process.checked(self.root, ["config", "user.email", "fixture@example.invalid"])
        for number in range(1, 4):
            (self.root / "hello.py").write_text(
                f"# user comment\ndef hello():\n    return {number}\n"
            )
            process.checked(self.root, ["add", "."])
            process.checked(self.root, ["commit", "-m", f"Change {number}"])
        head = process.checked(self.root, ["rev-parse", "HEAD"]).strip()
        run, status, state = self.run_mode("git-actions")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(len(state["git_jobs"]), 2)
        self.assertTrue(all(entry["status"] == "SUCCEEDED" for entry in state["git_jobs"]))
        self.assertEqual(process.checked(self.root, ["rev-parse", "HEAD^"]).strip(), head)
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        checkpoint = json.loads((run / "checkpoint.json").read_text())
        from countersign.application.git_state import git_metadata

        self.assertEqual(checkpoint["git_before"], git_metadata({"project": self.root}))
        self.assertIn("G0", (run / "01-plan/evidence-bindings.json").read_text())

    def test_git_policy_rejection_returns_feedback_and_workflow_continues(self):
        run, status, state = self.run_mode("git-denied")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(state["git_jobs"][0]["status"], "REJECTED")
        self.assertIn("REJECTED", (run / "01-plan/tool-result.md").read_text())
        self.assertEqual(state["stages"][0]["session_turns"], 2)

    def test_ssh_request_returns_results_to_the_same_workflow(self):
        response = dict(
            id="approved-ticket",
            status="SUCCEEDED",
            results=[dict(target="server-a", output="Linux", status="SUCCEEDED")],
        )
        with patch("countersign.executor.client.request", return_value=response) as request:
            run, status, state = self.run_mode("ssh-action")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(state["stages"][0]["status"], "RESULT_VALID")
        self.assertIn("Linux", (run / "01-plan/tool-result.md").read_text())
        self.assertEqual(state["execution_jobs"][0]["status"], "SUCCEEDED")
        self.assertIn("SSH execution", (run / "report.md").read_text())

    def test_ssh_wait_stop_resume_observes_same_ticket(self):
        def pending_request(payload):
            self.assertEqual(payload["operation"], "submit")
            (self.base / "result/stop.request").touch()
            return dict(id="same-ticket", status="PENDING_APPROVAL", results=[])

        with patch("countersign.executor.client.request", side_effect=pending_request) as request:
            with patch("countersign.application.execution_wait.time.sleep"):
                run, status, state = self.run_mode("ssh-action")
        self.assertEqual(status, "INTERRUPTED")
        self.assertEqual(request.call_count, 1)
        outcome = dict(
            id="same-ticket", status="SUCCEEDED", results=[dict(output="Linux", status="SUCCEEDED")]
        )
        with patch("countersign.executor.client.request", return_value=outcome) as request:
            _, status = execute_task(
                run / "00-input/task.md", self.settings, run_dir=run, resume=True
            )
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(request.call_args.args[0], dict(operation="status", id="same-ticket"))
        self.assertEqual(request.call_count, 1)

    def test_live_success_keeps_dirty_and_only_selected_preimages(self):
        run, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        self.assertEqual((self.root / "unrelated.txt").read_text(), "user dirty work\n")
        self.assertIn("# user comment", (self.root / "hello.py").read_text())
        self.assertEqual(list(state["preimages"]), ["project/hello.py"])
        self.assertFalse((run / "workspace").exists())
        self.assertEqual((self.root / ".git/HEAD").read_text(), "ref: refs/heads/main\n")
        self.assertIn("-    return 1", (run / "changes.diff").read_text())
        self.assertIn("--- " + str(self.root / "hello.py"), (run / "changes.diff").read_text())
        self.assertTrue((run / "report.md").exists())
        self.assertFalse(list(self.profiles.glob("countersign-*.md")))
        self.assertEqual(
            [a["stage"] for a in state["attempts"]],
            ["planner", "plan-reviewer", "implementer", "reviewer"],
        )
        suffix = hashlib.sha256(str(run).encode()).hexdigest()[:8]
        self.assertEqual(
            [a["agent"] for a in state["attempts"]],
            [
                f"countersign-planner-{suffix}",
                f"countersign-reviewer-{suffix}",
                f"countersign-implementer-{suffix}",
                f"countersign-reviewer-{suffix}",
            ],
        )
        self.assertEqual(len(list((run / "00-input/agents").glob("*.md"))), 3)
        self.assertTrue((run / "02-plan-review/agent.md").exists())
        self.assertTrue((run / "05-review/agent.md").exists())

    def test_jenkins_example(self):
        original = "pipeline {\n    agent any\n    stages { stage('Tests') { steps { sh 'pytest -q || true' } } }\n}\n"
        (self.root / "Jenkinsfile").write_text(original)
        run, status, state = self.run_mode("jenkins")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual((self.root / "Jenkinsfile").read_text(), original.replace(" || true", ""))
        self.assertEqual(state["changed_files"], ["project/Jenkinsfile"])
        self.assertEqual(state["checks"][0]["status"], "SKIPPED")

    def test_two_live_roots(self):
        secondary = self.base / "jenkins"
        secondary.mkdir()
        (secondary / "pipeline.groovy").write_text("old\n")
        self.task.write_text(
            "```countersign-task\n"
            + json.dumps({"roots": {"project": str(self.root), "jenkins": str(secondary)}})
            + "\n```\nFix both"
        )
        _, status, state = self.run_mode("multi")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual((secondary / "pipeline.groovy").read_text(), "new\n")
        self.assertEqual(
            set(state["changed_files"]), {"project/hello.py", "jenkins/pipeline.groovy"}
        )

    def test_one_file_cli(self):
        # Prepare settings through the same fixture, then exercise the public entry.
        self.run_mode()
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "countersign",
                str(self.task),
                "--settings",
                str(self.settings),
                "--run-dir",
                str(self.base / "cli-result"),
            ],
            cwd=BASE,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("READY_FOR_REVIEW", done.stdout)
        self.assertTrue((self.base / "cli-result/report.md").exists())

    def test_source_changes_apply_only_next_run(self):
        self.source = self.base / "role-source"
        self.source.mkdir()
        for role in ("planner", "implementer", "reviewer"):
            (self.source / (role + ".md")).write_bytes(
                (BASE / "countersign/agents" / (role + ".md")).read_bytes()
            )
        original = (self.source / "reviewer.md").read_text()
        changed = original + "\nNEW_INSTRUCTIONS_NEXT_RUN\n"

        def invoke(*args, **kwargs):
            result = real_run_agent(*args, **kwargs)
            (self.source / "reviewer.md").write_text(changed)
            return result

        with patch("countersign.interactions.session.run_agent", side_effect=invoke):
            run, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual((run / "00-input/agents/reviewer.md").read_text(), original)
        self.assertNotIn("NEW_INSTRUCTIONS_NEXT_RUN", (run / "05-review/agent.md").read_text())
        run2, status2 = execute_task(self.task, self.settings, run_dir=self.base / "next-run")
        self.assertEqual(status2, "READY_FOR_REVIEW")
        self.assertIn("NEW_INSTRUCTIONS_NEXT_RUN", (run2 / "05-review/agent.md").read_text())
        # Profile names are unique per run, so parallel runs never share permissions.
        self.assertNotEqual(
            state["attempts"][0]["agent"],
            json.loads((run2 / "run.json").read_text())["attempts"][0]["agent"],
        )

    def test_saved_plan_still_requires_independent_review(self):
        self.run_mode()
        saved = self.base / "saved.txt"
        saved.write_text("Saved earlier plan: change project/hello.py to return 2")
        run, status = execute_task(
            self.task, self.settings, run_dir=self.base / "imported", plan_response=saved
        )
        self.assertEqual(status, "READY_FOR_REVIEW")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(
            [a["stage"] for a in state["attempts"]],
            ["planner", "plan-reviewer", "implementer", "reviewer"],
        )
        header = json.loads((run / "01-plan/agent.md").read_text().split("---")[1])
        self.assertIsInstance(header["permission"]["read"], dict)
        self.assertIn("Saved earlier plan:", (run / "01-plan/request.md").read_text())

    def test_live_prompt_has_complete_schema(self):
        run, status, state = self.run_mode()
        prompt = (run / "01-plan/request.md").read_text()
        schema_text = prompt.split("Response schema:\n", 1)[1].split("\nContext:", 1)[0]
        schema = json.loads(schema_text)["oneOf"][0]
        self.assertIn("files_read", schema["properties"])
        self.assertIn("proposed_change_files", schema["properties"])
        self.assertNotIn("NEEDS_INFO", (run / "00-input/agents/planner.md").read_text())

    def test_full_long_task_reaches_all_roles(self):
        text = (
            self.task.read_text()
            + "\n"
            + 'Long task with shell ${COMPOSE[@]} and quotes "x".\n' * 150
            + "\nFINAL_REQUIREMENT_7"
        )
        self.task.write_text(text)
        run, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW")
        for stage in ("01-plan", "02-plan-review", "03-implement", "05-review"):
            request = (run / stage / "request.md").read_text()
            context = json.loads(request.split("Context:\n", 1)[1])
            self.assertTrue(
                request.startswith(
                    "# Task (verbatim)\n" + text + "\n\n# Orchestrator instructions\n"
                )
            )
            self.assertNotIn("task_chunks", context)
            self.assertLess(max(map(len, request.splitlines())), 2000)
            header = json.loads((run / stage / "agent.md").read_text().split("---")[1])
            self.assertEqual(header["permission"]["read"][str(run / "00-input/task.md")], "allow")
            self.assertNotIn(str(run / stage) + "/*", header["permission"]["read"])
            if stage != "01-plan":
                saved = str(run / "01-plan/result.json")
                self.assertIn(saved, context["saved_results"])
                self.assertEqual(header["permission"]["read"][saved], "allow")

    def test_incomplete_review_cannot_start_writer(self):
        run, status, state = self.run_mode("incomplete-review")
        self.assertEqual(status, "BLOCKED")
        self.assertNotIn("implementer", [a["stage"] for a in state["attempts"]])
        self.assertEqual(state["stages"][1]["status"], "RESULT_VALID")
        self.assertEqual(state["stages"][1]["verdict"], "BLOCKED")
        self.assertIn("Task was truncated", (run / "report.md").read_text())
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_both_reviews_keep_unverified_evidence(self):
        run, status, state = self.run_mode()
        self.assertEqual(len(state["review_limits"]), 2)
        report = (run / "report.md").read_text()
        self.assertIn("Review limitations: 02-plan-review", report)
        self.assertIn("Review limitations: 05-review", report)
        request = (run / "05-review/request.md").read_text()
        context = json.loads(request.split("Context:\n", 1)[1])
        self.assertEqual(context["prior_plan_review"]["unverified"], ["Runtime not run"])
        self.assertEqual(context["diff_file"], str(run / "changes.diff"))

    def test_already_satisfied_task_needs_no_writer(self):
        (self.root / "hello.py").write_text("def hello():\n    return 2\n")
        run, status, state = self.run_mode("no-change")
        self.assertEqual(status, "NO_CHANGES_REQUIRED")
        self.assertEqual(state["changed_files"], [])
        self.assertEqual([a["stage"] for a in state["attempts"]], ["planner", "plan-reviewer"])
        self.assertEqual(state["checks"], [])
        self.assertEqual(len(state["review_limits"]), 1)
        self.assertIn("Runtime not run", (run / "report.md").read_text())
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "countersign",
                str(self.task),
                "--settings",
                str(self.settings),
                "--run-dir",
                str(self.base / "cli-no-change"),
            ],
            cwd=BASE,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("NO_CHANGES_REQUIRED", done.stdout)
        self.assertIn("Result [02-plan-review]: APPROVE", done.stdout)

    def test_no_change_requires_independent_approval(self):
        run, status, state = self.run_mode("no-change-rejected")
        self.assertEqual(status, "BLOCKED")
        self.assertEqual([a["stage"] for a in state["attempts"]], ["planner", "plan-reviewer"])
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_parent_search_once_continues_same_session_without_widening_permissions(self):
        run, status, state = self.run_mode("parent-once")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(state["stages"][1]["status"], "RESULT_VALID")
        self.assertEqual(state["stages"][1]["session_turns"], 2)
        profile = json.loads((run / "02-plan-review/agent.md").read_text().split("---")[1])
        self.assertNotIn(str(self.root.parent) + "/*", profile["permission"]["external_directory"])
        self.assertIn("DECLINED", (run / "02-plan-review/tool-result.md").read_text())

    def test_repeated_denied_search_obeys_stage_time_without_writer(self):
        run, status, state = self.run_mode("parent-twice", read_retries=0, timeout_seconds=1)
        self.assertEqual(status, "TIMEOUT")
        self.assertEqual([a["stage"] for a in state["attempts"]], ["planner", "plan-reviewer"])
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_missing_read_does_not_block_valid_result_or_independent_review(self):
        run, status, state = self.run_mode("missing-read")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(state["stages"][0]["errors"], [])
        warning = state["stages"][0]["warnings"][0]
        self.assertEqual(warning["tool"], "read")
        self.assertIn("Unsuccessful exploratory read", warning["resolution"])
        self.assertEqual(state["attempts"][1]["stage"], "plan-reviewer")
        self.assertIn("File not found", (run / "report.md").read_text())

    def test_corrected_offset_keeps_warning_and_reaches_independent_review(self):
        run, status, state = self.run_mode("offset-recovered")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(state["stages"][0]["errors"], [])
        self.assertTrue(
            state["stages"][0]["warnings"][0]["recovered_by"]["call_id"].endswith("corrected")
        )
        self.assertIn("Recovered by a later full read", (run / "report.md").read_text())
        self.assertEqual(state["attempts"][1]["stage"], "plan-reviewer")

    def test_timeout_passes_attributed_read_evidence_to_retry(self):
        run, status, state = self.run_mode("timeout-evidence")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(state["stages"][1]["mode"], "research-recovery")
        self.assertEqual(state["stages"][1]["inputs"]["recovery"], "02-plan/recovery.md")
        evidence = (run / "02-plan/recovery.md").read_text()
        self.assertIn("01-plan/events.jsonl", evidence)
        self.assertIn("return 1", evidence)
        self.assertIn("original_chars", evidence)

    def test_timeout_does_not_consume_format_repair(self):
        run, status, state = self.run_mode("timeout-then-invalid", format_repair_tools="read")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(
            [a["status"] for a in state["attempts"][:3]], ["TIMEOUT", "INVALID_RESULT", "OK"]
        )
        self.assertEqual(len(state["attempts"]), 6)
        self.assertIn("FORMAT REPAIR ONLY", (run / "03-plan/request.md").read_text())
        # The repair may re-read the recovery evidence its saved response cites.
        recovery = run / "02-plan/recovery.md"
        self.assertTrue(recovery.is_file())
        repair = json.loads((run / "03-plan/agent.md").read_text().split("---")[1])["permission"]
        first = json.loads((run / "02-plan/agent.md").read_text().split("---")[1])["permission"]
        self.assertEqual(repair["read"].get(str(recovery)), "allow")
        self.assertEqual(first["read"].get(str(recovery)), "allow")
        self.assertNotIn(str(run / "03-plan/recovery.md"), repair["read"])

    def test_imported_plan_is_revalidated_under_current_contract(self):
        self.run_mode()
        plan = dict(
            status="PLAN_READY",
            summary="fix",
            steps=["Return 2"],
            files_read=["project/hello.py"],
            proposed_change_files=["project/hello.py"],
        )
        saved = self.base / "valid-plan.txt"
        saved.write_text('Shell example: "${COMPOSE[@]}" build jobmanager\n' + json.dumps(plan))
        run, status = execute_task(
            self.task, self.settings, run_dir=self.base / "parsed-import", plan_response=saved
        )
        self.assertEqual(status, "READY_FOR_REVIEW")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(
            [a["stage"] for a in state["attempts"]],
            ["planner", "plan-reviewer", "implementer", "reviewer"],
        )
        self.assertEqual(state["contract_version"], 1)
        self.assertIn("imported_draft", (run / "01-plan/request.md").read_text())

    def test_permission_denied_retains_tool_input_after_operator_declines(self):
        run, status, state = self.run_mode("denied", read_retries=0, timeout_seconds=1)
        self.assertEqual(status, "TIMEOUT")
        events = (run / "02-plan-review/events.jsonl").read_text()
        self.assertIn("/outside/skills/SKILL.md", events)
        self.assertIn("DECLINED", events)
        self.assertFalse((run / "02-plan-review/result.json").exists())

    def test_ordered_layout_has_one_result_per_stage(self):
        run, status, state = self.run_mode()
        self.assertEqual(
            [s["directory"] for s in state["stages"]],
            ["01-plan", "02-plan-review", "03-implement", "04-check", "05-review"],
        )
        self.assertEqual(
            {p.name for p in run.iterdir()},
            {
                "00-input",
                "01-plan",
                "02-plan-review",
                "03-implement",
                "04-check",
                "05-review",
                "run.json",
                "report.md",
                "changes.diff",
                "checkpoint.json",
                "evidence.json",
                "observations.json",
                "budgets.json",
            },
        )
        for record in state["stages"]:
            directory = run / record["directory"]
            self.assertTrue((directory / "result.json").exists())
            if record["mode"] == "model":
                self.assertEqual(
                    {p.name for p in directory.iterdir()},
                    {
                        "stage.json",
                        "agent.md",
                        "access.json",
                        "permissions.log",
                        "request.md",
                        "tool-result.md",
                        "response.raw.txt",
                        "response-object.json",
                        "result.json",
                        "events.jsonl",
                        "stderr.log",
                        "activity.json",
                        "telemetry.json",
                        "evidence-bindings.json",
                    },
                )
        self.assertEqual(state["stages"][1]["inputs"]["plan"], "01-plan/result.json")
        self.assertEqual(state["stages"][1]["role"], "reviewer")
        self.assertEqual(state["stages"][1]["verdict"], "APPROVE")

    def test_rendered_paths_are_absolute_without_double_alias(self):
        roots = {"qa": self.root, "jenkins": self.base / "jenkins"}
        value = {
            "files_read": ["qa/hello.py"],
            "steps": ["Read qa/hello.py and jenkins/pipeline.groovy"],
            "absolute": str(self.root / "hello.py"),
        }
        rendered = tool_paths(value, roots)
        self.assertEqual(rendered["files_read"], [str(self.root / "hello.py")])
        self.assertEqual(rendered["absolute"], value["absolute"])
        self.assertNotIn(str(self.root / "qa"), rendered["steps"][0])
        self.assertEqual(value["files_read"], ["qa/hello.py"])

    def test_absolute_plan_output_is_safely_normalized(self):
        value = dict(
            status="PLAN_READY",
            summary="fix",
            steps=["fix"],
            files_read=[str(self.root / "hello.py")],
            proposed_change_files=[str(self.root / "hello.py")],
        )
        value = canonical_plan(value, {"qa": self.root})
        validate_plan(value, {"qa": self.root}, self.task)
        self.assertEqual(value["proposed_change_files"], ["qa/hello.py"])
        value["proposed_change_files"] = ["/outside/file"]
        with self.assertRaises(ValueError):
            validate_plan(canonical_plan(value, {"qa": self.root}), {"qa": self.root}, self.task)

    def test_many_calls_remain_metrics_without_extra_stage(self):
        run, status, state = self.run_mode("many-calls")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(state["stages"][0]["mode"], "model")
        self.assertNotIn("tools", state["stages"][0]["budget"])
        self.assertEqual(state["attempts"][1]["stage"], "plan-reviewer")
        self.assertGreater(state["attempts"][0]["tool_calls"], 300)

    def test_budget_stop_continues_with_explicit_grant(self):
        run, status, state = self.run_mode("read-retry", max_stage_attempts=1)
        self.assertEqual(status, "STAGE_BUDGET_EXCEEDED")
        self.assertEqual(len(state["stages"]), 2)
        settings = json.loads(self.settings.read_text())
        settings["max_stage_attempts"] = 6
        self.settings.write_text(json.dumps(settings))
        _, status = execute_task(self.task, self.settings, run_dir=run, resume="extend")
        self.assertEqual(status, "READY_FOR_REVIEW", (run / "report.md").read_text())
        ledger = json.loads((run / "budgets.json").read_text())
        self.assertEqual(len(ledger["grants"]), 1)
        self.assertIn("01-plan", ledger["attempts"])
        self.assertIn("return 2", (self.root / "hello.py").read_text())

    def test_git_metadata_read_does_not_authorize_edit(self):
        plan = dict(
            status="PLAN_READY",
            summary="Read metadata",
            steps=[],
            files_read=["project/.git/HEAD"],
            proposed_change_files=[],
        )
        validate_plan(plan, {"project": self.root}, self.task)
        plan["proposed_change_files"] = ["project/.git/HEAD"]
        with self.assertRaisesRegex(ValueError, "Protected path"):
            validate_plan(plan, {"project": self.root}, self.task)

    def test_new_file(self):
        run, status, state = self.run_mode("new")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertIsNone(state["preimages"]["project/new.py"])
        self.assertTrue((self.root / "new.py").exists())

    def test_read_retry(self):
        _, status, state = self.run_mode("read-retry")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(len(state["attempts"]), 5)

    def test_invalid_read_result_retry(self):
        _, status, state = self.run_mode("invalid-once")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(state["attempts"][0]["status"], "INVALID_RESULT")
        run = self.base / "result"
        profile = (run / "02-plan/agent.md").read_text()
        header = json.loads(profile.split("---")[1])
        for tool in ("read", "glob", "grep", "list", "edit", "bash", "task"):
            self.assertEqual(header["permission"][tool], "deny")
        retry_prompt = (run / "02-plan/request.md").read_text()
        self.assertIn("missing arrays", retry_prompt)
        self.assertIn("FORMAT REPAIR ONLY", retry_prompt)

    def test_structured_steps_are_validated_without_model_retry(self):
        run, status, state = self.run_mode("structured-steps")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(len(state["attempts"]), 4)
        plan = json.loads((run / "01-plan/result.json").read_text())
        self.assertIsInstance(plan["steps"][0], dict)
        self.assertEqual(plan["steps"][0]["action"], "Return 2")
        self.assertEqual(plan["proposed_change_files"], [str(self.root / "hello.py")])
        self.assertIn('"action"', (run / "01-plan/response.raw.txt").read_text())

    def test_format_repair_rejected_unavailable_calls_keep_valid_conclusion(self):
        run, status, state = self.run_mode("format-unavailable")
        self.assertEqual(status, "READY_FOR_REVIEW")
        repaired = state["stages"][1]
        self.assertEqual(repaired["mode"], "format-repair")
        self.assertEqual(repaired["errors"], [])
        self.assertEqual(len(repaired["tool_errors"]), 2)
        self.assertEqual(len(repaired["warnings"]), 2)
        self.assertEqual(repaired["status"], "RESULT_VALID")
        profile = (run / "02-plan/agent.md").read_text()
        self.assertIn("format converter", profile)

    def continue_with_ok_model(self, run):
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        settings["timeout_seconds"] = 5
        self.settings.write_text(json.dumps(settings))
        return execute_task(run / "00-input/task.md", self.settings, run_dir=run, resume=True)

    def test_explicit_resume_partial_writer_preserves_plan_and_original_diff(self):
        run, status, state = self.run_mode("writer-timeout")
        self.assertEqual(status, "TIMEOUT")
        old_steps = len(state["stages"])
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "READY_FOR_REVIEW")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(
            [s["stage"] for s in state["stages"][old_steps:]], ["implementer", "check", "reviewer"]
        )
        request = (run / state["stages"][old_steps]["directory"] / "request.md").read_text()
        self.assertIn("Do not blindly replay edits", request)
        self.assertIn("-    return 1", (run / "changes.diff").read_text())

    def test_resume_final_review_does_not_repeat_implementation(self):
        run, status, state = self.run_mode("review-timeout")
        self.assertEqual(status, "TIMEOUT")
        old_steps = len(state["stages"])
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "READY_FOR_REVIEW")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual([s["stage"] for s in state["stages"][old_steps:]], ["reviewer"])

    def test_denied_review_recovers_without_repeating_writer(self):
        run, status, state = self.run_mode("review-denied-once")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(sum(s["stage"] == "implementer" for s in state["stages"]), 1)
        self.assertEqual(state["stages"][-1]["session_turns"], 2)
        request = (run / state["stages"][-1]["directory"] / "events.jsonl").read_text()
        self.assertIn("/wrong/admin/ci-pipelines", request)
        self.assertIn(str(self.root), request)

    def test_permission_checkpoint_exposes_resume_and_only_runs_review(self):
        from countersign.application.checkpoints import resume_available

        run, status, state = self.run_mode(
            "review-denied-always", read_retries=0, timeout_seconds=1
        )
        self.assertEqual(status, "TIMEOUT")
        self.assertTrue(resume_available(run, state)[0])
        old_steps = len(state["stages"])
        before = (self.root / "hello.py").read_bytes()
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "READY_FOR_REVIEW")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual([s["stage"] for s in state["stages"][old_steps:]], ["reviewer"])
        self.assertEqual((self.root / "hello.py").read_bytes(), before)

    def test_permission_resume_still_rejects_source_changes(self):
        run, _, state = self.run_mode("review-denied-always", read_retries=0, timeout_seconds=1)
        old_steps = len(state["stages"])
        (self.root / "unrelated.txt").write_text("new user work")
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "BLOCKED")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(len(state["stages"]), old_steps)

    def test_resume_refuses_changed_source(self):
        run, status, state = self.run_mode("writer-timeout")
        old_steps = len(state["stages"])
        (self.root / "unrelated.txt").write_text("new user work")
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "BLOCKED")
        self.assertEqual((self.root / "unrelated.txt").read_text(), "new user work")
        self.assertEqual(len(json.loads((run / "run.json").read_text())["stages"]), old_steps)

    def test_missing_checkpoint_cannot_continue(self):
        run, status, state = self.run_mode("planner-timeout")
        self.assertEqual(status, "TIMEOUT")
        (run / "checkpoint.json").unlink()
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "BLOCKED")
        self.assertIn("No safe checkpoint", json.loads((run / "run.json").read_text())["summary"])

    def test_writer_timeout_preserves_and_does_not_repeat(self):
        _, status, state = self.run_mode("writer-timeout")
        self.assertEqual(status, "TIMEOUT")
        self.assertEqual(len(state["attempts"]), 3)
        self.assertIn("return 2", (self.root / "hello.py").read_text())

    def test_review_repair(self):
        _, status, state = self.run_mode("review-repair")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(len(state["attempts"]), 6)

    def test_plan_repair(self):
        _, status, state = self.run_mode("plan-repair")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(len(state["attempts"]), 6)

    def test_syntax_repair(self):
        _, status, state = self.run_mode("syntax")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(len(state["attempts"]), 5)

    def verify_command(self, code, **options):
        return dict(cwd=str(self.root), argv=[sys.executable, "-c", code], **options)

    def test_settings_verify_command_passes_and_keeps_output(self):
        code = "print('verified', open('hello.py').read().count('return 2'))"
        run, status, state = self.run_mode("ok", verify_commands=[self.verify_command(code)])
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        command = state["checks"][-1]
        self.assertEqual(command["status"], "PASS")
        self.assertEqual(command["cwd"], str(self.root))
        log = next(run.glob("*-check/verify-01.log"))
        self.assertIn("verified 1", log.read_text())
        frozen = json.loads((run / "00-input/settings.json").read_text())
        self.assertEqual(frozen["verify_commands"][0]["timeout_seconds"], 600)

    def test_failed_verify_command_returns_output_to_bounded_repair(self):
        failing = self.verify_command("import sys; print('boom'); sys.exit(3)")
        run, status, state = self.run_mode("ok", verify_commands=[failing], max_repairs=1)
        self.assertEqual(status, "CHECK_FAILED")
        self.assertEqual(len(list(run.glob("*-check"))), 2)
        self.assertIn("exit 3", state["checks"][-1]["detail"])
        self.assertIn("boom", state["checks"][-1]["detail"])

    def test_verify_command_writing_sources_stops_the_run(self):
        writer = self.verify_command("open('generated.txt', 'w').write('x')")
        _, status, state = self.run_mode("ok", verify_commands=[writer])
        self.assertEqual(status, "BLOCKED")
        self.assertIn("verification commands must not write", state["summary"])

    def test_verify_commands_are_validated_with_settings(self):
        for entry in (
            dict(cwd="relative", argv=["python3"]),
            dict(cwd=str(self.root), argv=["git", "status"]),
            dict(cwd=str(self.root), argv=[]),
            dict(cwd=str(self.root), argv=["python3"], shell=True),
        ):
            self.settings.write_text(json.dumps(dict(verify_commands=[entry])))
            with self.assertRaises(ValueError):
                configuration(self.task, self.settings)

    def isolated_repository(self):
        from countersign.git import process

        (self.root / ".git/HEAD").unlink()
        (self.root / ".git").rmdir()
        process.checked(self.root, ["init", "-b", "main"])
        process.checked(self.root, ["config", "user.name", "Fixture"])
        process.checked(self.root, ["config", "user.email", "fixture@example.invalid"])
        process.checked(self.root, ["add", "."])
        process.checked(self.root, ["commit", "-m", "Initial"])
        header = {"roots": {"project": str(self.root)}, "isolation": "worktree"}
        self.task.write_text(f"```countersign-task\n{json.dumps(header)}\n```\nReturn 2")
        return process

    def test_worktree_isolation_leaves_the_source_checkout_untouched(self):
        process = self.isolated_repository()
        probe = self.verify_command("import os; print('cwd', os.getcwd())")
        run, status, state = self.run_mode(
            "ok", worktree_base=str(self.base / "worktrees"), verify_commands=[probe]
        )
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        entry = state["worktrees"]["project"]
        worktree = Path(entry["worktree"])
        self.assertEqual(worktree, (self.base / "worktrees" / run.name / "project").resolve())
        self.assertEqual(entry["branch"], f"countersign/{run.name}")
        self.assertEqual(state["roots"], {"project": str(worktree)})
        self.assertIn("return 1", (self.root / "hello.py").read_text())
        self.assertIn("return 2", (worktree / "hello.py").read_text())
        self.assertEqual(process.checked(self.root, ["status", "--porcelain"]), "")
        report = (run / "report.md").read_text()
        self.assertIn("## Isolated worktrees", report)
        self.assertIn("edited in isolated worktrees", report)
        log = next(run.glob("*-check/verify-01.log")).read_text()
        self.assertIn(f"cwd {worktree}", log)
        from countersign.application.worktree_isolation import source_roots

        self.assertEqual(source_roots(state), [{"alias": "project", "path": str(self.root)}])

    def test_isolated_run_continues_in_its_worktree(self):
        self.isolated_repository()
        run, status, state = self.run_mode("review-timeout", worktree_base=str(self.base / "wt"))
        self.assertEqual(status, "TIMEOUT")
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "READY_FOR_REVIEW")
        resumed = json.loads((run / "run.json").read_text())
        self.assertEqual(resumed["worktrees"], state["worktrees"])
        self.assertEqual(len(list((self.base / "wt").iterdir())), 1)

    def test_isolation_needs_a_repository_top_level(self):
        self.isolated_repository()
        nested = self.root / "nested"
        nested.mkdir()
        header = {"roots": {"project": str(nested)}, "isolation": "worktree"}
        self.task.write_text(f"```countersign-task\n{json.dumps(header)}\n```\nReturn 2")
        with self.assertRaisesRegex(ValueError, "top-level"):
            self.run_mode("ok", worktree_base=str(self.base / "wt"))
        header["isolation"] = "copy"
        self.task.write_text(f"```countersign-task\n{json.dumps(header)}\n```\nReturn 2")
        with self.assertRaisesRegex(ValueError, "isolation"):
            configuration(self.task)

    def test_linked_worktree_ignores_other_branches_but_tracks_its_own(self):
        from countersign.application.git_state import git_metadata

        process = self.isolated_repository()
        linked = self.base / "linked"
        process.checked(self.root, ["worktree", "add", "-b", "work", str(linked), "HEAD"])
        before = git_metadata({"linked": linked})
        (self.root / "unrelated.txt").write_text("main checkout keeps working\n")
        process.checked(self.root, ["commit", "-am", "Main checkout commit"])
        self.assertEqual(git_metadata({"linked": linked}), before)
        (linked / "hello.py").write_text("changed\n")
        process.checked(linked, ["commit", "-am", "Worktree commit"])
        self.assertNotEqual(git_metadata({"linked": linked}), before)

    def test_implementer_prose_gets_one_format_repair_without_edits(self):
        run, status, state = self.run_mode("writer-prose")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        modes = [(stage["stage"], stage["mode"]) for stage in state["stages"]]
        self.assertIn(("implementer", "format-repair"), modes)
        repair = next(stage for stage in state["stages"] if stage["mode"] == "format-repair")
        request = (run / repair["directory"] / "request.md").read_text()
        self.assertIn("This pass cannot edit files", request)

    def test_failed_writer_response_can_continue_with_an_operator_note(self):
        run, status, state = self.run_mode("writer-prose-always")
        self.assertEqual(status, "INVALID_RESULT")
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        self.settings.write_text(json.dumps(settings))
        note = "python3 is installed now; run the unit tests through LOCAL_REQUEST."
        _, status = execute_task(
            run / "00-input/task.md", self.settings, run_dir=run, resume=True, note=note
        )
        self.assertEqual(status, "READY_FOR_REVIEW")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(state["continuations"][-1]["operator_note"], note)
        resumed = state["stages"][len(state["stages"]) - 3]
        self.assertEqual(resumed["stage"], "implementer")
        request = (run / resumed["directory"] / "request.md").read_text()
        self.assertIn(note, request)
        self.assertIn("Do not blindly replay edits", request)

    def test_blocked_format_repair_gets_one_full_attempt(self):
        run, status, state = self.run_mode("repair-blocked")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = [stage for stage in state["stages"] if stage["stage"] == "planner"]
        self.assertEqual(
            [stage["mode"] for stage in planner], ["model", "format-repair", "research-recovery"]
        )
        request = (run / planner[-1]["directory"] / "request.md").read_text()
        self.assertIn("PREVIOUS FINAL RESPONSE WAS INVALID: Missing fields", request)

    def test_large_change_waits_for_the_operator(self):
        run, status, state = self.run_mode("ok", max_change_lines=1)
        self.assertEqual(status, "CHANGE_LIMIT_EXCEEDED", state.get("summary"))
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        self.assertNotIn("checks", state["results"])
        decisions = [
            dict(decision="alternative", alternative="Keep the edit to one line"),
            dict(decision="allow", alternative=""),
        ]
        requests = []

        def decide(_run, request):
            requests.append(request)
            return decisions.pop(0)

        (self.root / "hello.py").write_text("# user comment\ndef hello():\n    return 1\n")
        with patch("countersign.interactions.approvals.wait", side_effect=decide):
            run, status = execute_task(self.task, self.settings, run_dir=self.base / "second")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(requests[0]["status"], "CHANGE_LIMIT")
        self.assertEqual(requests[0]["lines"], 2)
        self.assertEqual(state["approved_change"], dict(lines=2, files=1))
        stages = [stage["stage"] for stage in state["stages"]]
        self.assertEqual(stages.count("implementer"), 2)
        second = [stage for stage in state["stages"] if stage["stage"] == "implementer"][1]
        self.assertIn(
            "Keep the edit to one line", (run / second["directory"] / "request.md").read_text()
        )

    def test_design_discussion_leaves_a_reviewed_design_document(self):
        header = {"roots": {"project": str(self.root)}, "design": True}
        self.task.write_text(f"```countersign-task\n{json.dumps(header)}\n```\nDesign caching")
        run, status, state = self.run_mode("no-change")
        self.assertEqual(status, "NO_CHANGES_REQUIRED", state.get("summary"))
        self.assertEqual((run / "design.md").read_text(), "Current source already returns 2\n")
        self.assertIn("[Design document](design.md)", (run / "report.md").read_text())
        frozen = json.loads((run / "00-input/settings.json").read_text())
        self.assertIn("max_change_lines", frozen)

    def test_unsafe_permissions_no_model(self):
        _, status, state = self.run_mode("unsafe")
        self.assertEqual(status, "BLOCKED")
        self.assertEqual(state["attempts"], [])
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_scope_stops_no_revert(self):
        _, status, state = self.run_mode("scope")
        self.assertEqual(status, "BLOCKED")
        self.assertEqual((self.root / "unrelated.txt").read_text(), "corrupted")
        self.assertIn("project/unrelated.txt", state["changed_files"])

    def test_git_mutation_detected(self):
        _, status, state = self.run_mode("git")
        self.assertEqual(status, "BLOCKED")
        self.assertEqual(state["stage"], "implementer")

    def test_readonly_mutation_detected(self):
        _, status, state = self.run_mode("readonly-write")
        self.assertEqual(status, "BLOCKED")
        self.assertEqual(len(state["attempts"]), 1)

    def test_forbidden_plan(self):
        _, status, state = self.run_mode("badpath")
        self.assertEqual(status, "INVALID_RESULT")
        self.assertEqual(len(state["attempts"]), 2)

    def test_symlink_and_metadata_paths_rejected(self):
        (self.root / "link").symlink_to(self.base, target_is_directory=True)
        for path in ["project/link/new", "project/.git/config", "project/../foo", "project/x*"]:
            with self.assertRaises(ValueError):
                safe_file(path, {"project": self.root})

    def test_task_inside_repo_infers_root(self):
        task = self.root / "task.md"
        task.write_text("Fix it")
        config = configuration(task)
        self.assertEqual(config["roots"], {"project": self.root})

    def test_unknown_contract_cannot_continue(self):
        run, status, state = self.run_mode("review-timeout")
        self.assertEqual(status, "TIMEOUT")
        state["contract_version"] = 2
        (run / "run.json").write_text(json.dumps(state))
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "BLOCKED")
        self.assertIn(
            "Unsupported contract version", json.loads((run / "run.json").read_text())["summary"]
        )
        self.assertIn("return 2", (self.root / "hello.py").read_text())

    def test_prose_with_explicit_block_stops_without_format_repair_or_writes(self):
        run, status, state = self.run_mode("prose-block")
        self.assertEqual(status, "BLOCKED")
        self.assertEqual(len(state["attempts"]), 1)
        self.assertTrue((run / "01-plan/blocked-draft.json").exists())
        self.assertIn("return 1", (self.root / "hello.py").read_text())


if __name__ == "__main__":
    unittest.main()
