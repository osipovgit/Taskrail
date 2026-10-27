import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from live_fixture import BASE, LiveFixture

from taskrail.application.live import execute_task
from taskrail.application.plan_validation import canonical_plan, validate_plan
from taskrail.application.planned_paths import safe_file
from taskrail.application.task_config import configuration
from taskrail.core.paths import tool_paths
from taskrail.infrastructure.runner import run_agent as real_run_agent
from taskrail.interactions.session import MAX_RESULT_CORRECTIONS


class LiveTests(LiveFixture, unittest.TestCase):
    def test_large_reports_repair_together_without_a_new_planner_session(self):
        text = self.root / "issues.txt"
        text.write_text("".join(f"Finding {number}\n" for number in range(1, 1046)))
        report = self.root / "report.json"
        report.write_text(json.dumps([dict(rule="test", line=number) for number in range(300)]))
        original = report.read_bytes()
        run, status, state = self.run_mode("report-repair")
        self.assertEqual(status, "NO_CHANGES_REQUIRED", state.get("summary"))
        planner = [entry for entry in state["stages"] if entry["stage"] == "planner"]
        self.assertEqual(len(planner), 1)
        self.assertEqual(planner[0]["session_turns"], 2)
        self.assertEqual(state["stages"][-1]["stage"], "plan-reviewer")
        correction = (run / "01-plan/tool-result.md").read_text()
        self.assertIn("Evidence E1", correction)
        self.assertIn("Evidence E2", correction)
        self.assertIn("source-views", correction)
        proofs = json.loads((run / "01-plan/evidence-bindings.json").read_text())
        self.assertGreater(len(proofs[0]["observations"]), 1)
        self.assertEqual(proofs[1]["source_view"]["source_path"], str(report))
        self.assertEqual(report.read_bytes(), original)

    def test_git_history_and_revert_complete_the_workflow(self):
        from taskrail.git import process

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
        from taskrail.application.git_state import git_metadata

        self.assertEqual(checkpoint["git_before"], git_metadata({"project": self.root}))
        review = json.loads((run / "05-review/response-object.json").read_text())
        outputs = {
            job["output_file"] for job in json.loads((run / "git-execution.json").read_text())
        }
        self.assertLessEqual(outputs, {claim["path"] for claim in review["evidence"]})

    def test_resolved_source_overwrite_keeps_user_edits_and_independent_review(self):
        source = self.root / "hello.py"
        original = "# inserted before the function\n\n" + source.read_text()
        source.write_text(original)
        run, status, state = self.run_mode("write-recovered")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(source.read_text(), original.replace("return 1", "return 2"))
        self.assertEqual((self.root / "unrelated.txt").read_text(), "user dirty work\n")
        writer = [entry for entry in state["attempts"] if entry["stage"] == "implementer"]
        self.assertEqual(len(writer), 1)
        self.assertEqual(writer[0]["errors"], [])
        warning = writer[0]["warnings"][0]
        self.assertIn("read", warning["recovered_by"])
        stages = state["stages"]
        self.assertEqual(stages[-1]["stage"], "reviewer")
        self.assertEqual(stages[-1]["status"], "RESULT_VALID")
        self.assertIn(
            "Recovered by a later read and successful write", (run / "report.md").read_text()
        )

    def test_source_overwrite_recovery_never_hides_stops_or_replays_writes(self):
        cases = (
            ("write-unresolved", "TOOL_ERROR"),
            ("write-context", "CONTEXT_EXCEEDED"),
            ("write-scope", "BLOCKED"),
        )
        for mode, expected in cases:
            with self.subTest(mode=mode):
                self.setUp()
                _, status, state = self.run_mode(mode)
                self.assertEqual(status, expected, state.get("summary"))
                writer = [entry for entry in state["stages"] if entry["stage"] == "implementer"]
                self.assertEqual(len(writer), 1)
                self.assertEqual(writer[0]["session_turns"], 1)
                self.assertNotIn("reviewer", [entry["stage"] for entry in state["stages"]])
                if mode == "write-unresolved":
                    self.assertIn("return 1", (self.root / "hello.py").read_text())
                if mode == "write-scope":
                    self.assertIn("Scope violation", state["summary"])

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
        with patch("taskrail.executor.client.request", return_value=response) as request:
            run, status, state = self.run_mode("ssh-action")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(state["stages"][0]["status"], "RESULT_VALID")
        self.assertIn("Linux", (run / "01-plan/tool-result.md").read_text())
        self.assertEqual(state["execution_jobs"][0]["status"], "SUCCEEDED")
        self.assertIn("SSH and Jenkins execution", (run / "report.md").read_text())

    def test_ssh_wait_stop_resume_observes_same_ticket(self):
        def pending_request(payload):
            self.assertEqual(payload["operation"], "submit")
            (self.base / "result/stop.request").touch()
            return dict(id="same-ticket", status="PENDING_APPROVAL", results=[])

        with (
            patch("taskrail.executor.client.request", side_effect=pending_request) as request,
            patch("taskrail.application.execution_wait.time.sleep"),
        ):
            run, status, _state = self.run_mode("ssh-action")
        self.assertEqual(status, "INTERRUPTED")
        self.assertEqual(request.call_count, 1)
        outcome = dict(
            id="same-ticket", status="SUCCEEDED", results=[dict(output="Linux", status="SUCCEEDED")]
        )
        with patch("taskrail.executor.client.request", return_value=outcome) as request:
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
        self.assertFalse(list(self.profiles.glob("taskrail-*.md")))
        self.assertEqual(
            [a["stage"] for a in state["attempts"]],
            ["planner", "plan-reviewer", "implementer", "reviewer"],
        )
        suffix = hashlib.sha256(str(run).encode()).hexdigest()[:8]
        self.assertEqual(
            [a["agent"] for a in state["attempts"]],
            [
                f"taskrail-planner-{suffix}",
                f"taskrail-reviewer-{suffix}",
                f"taskrail-implementer-{suffix}",
                f"taskrail-reviewer-{suffix}",
            ],
        )
        self.assertEqual(len(list((run / "00-input/agents").glob("*.md"))), 3)
        self.assertTrue((run / "02-plan-review/agent.md").exists())
        self.assertTrue((run / "05-review/agent.md").exists())

    def test_jenkins_example(self):
        original = "pipeline {\n    agent any\n    stages { stage('Tests') { steps { sh 'pytest -q || true' } } }\n}\n"
        (self.root / "Jenkinsfile").write_text(original)
        _run, status, state = self.run_mode("jenkins")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual((self.root / "Jenkinsfile").read_text(), original.replace(" || true", ""))
        self.assertEqual(state["changed_files"], ["project/Jenkinsfile"])
        self.assertEqual(state["checks"][0]["status"], "SKIPPED")

    def test_two_live_roots(self):
        secondary = self.base / "jenkins"
        secondary.mkdir()
        (secondary / "pipeline.groovy").write_text("old\n")
        self.task.write_text(
            "```taskrail-task\n"
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
                "taskrail",
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
                (BASE / "taskrail/agents" / (role + ".md")).read_bytes()
            )
        original = (self.source / "reviewer.md").read_text()
        changed = original + "\nNEW_INSTRUCTIONS_NEXT_RUN\n"

        def invoke(*args, **kwargs):
            result = real_run_agent(*args, **kwargs)
            (self.source / "reviewer.md").write_text(changed)
            return result

        with patch("taskrail.interactions.session.run_agent", side_effect=invoke):
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
        run, _status, _state = self.run_mode()
        prompt = (run / "02-plan-review/request.md").read_text()
        schemas = prompt.split("Schemas, one per line:\n", 1)[1].split("\nContext:", 1)[0]
        schema = json.loads(schemas.splitlines()[0])
        self.assertNotIn("ACTION_REQUEST", schemas)
        self.assertIn("findings", schema["properties"])
        self.assertNotIn("quote", json.dumps(schema))
        planning = (run / "01-plan/request.md").read_text()
        self.assertIn(f"PLAN FILE: your result is the Markdown file {run / 'plan.md'}", planning)
        self.assertIn("[R1]\nReturn 2", planning)
        self.assertEqual(planning.count("Return 2"), 1)
        requests = planning.split("Request schemas, one per line:\n", 1)[1].split("\nContext:")[0]
        self.assertEqual(
            [json.loads(line)["properties"]["status"]["const"] for line in requests.splitlines()],
            ["GIT_REQUEST", "LOCAL_REQUEST"],
        )
        self.assertIn("Decision: single", (run / "01-plan/plan.md").read_text())
        self.assertNotIn("NEEDS_INFO", (run / "00-input/agents/planner.md").read_text())

    def test_full_long_task_reaches_all_roles(self):
        text = (
            self.task.read_text()
            + "\n"
            + 'Long task with shell ${COMPOSE[@]} and quotes "x".\n' * 150
            + "\nFINAL_REQUIREMENT_7"
        )
        self.task.write_text(text)
        run, status, _state = self.run_mode(model_context_tokens=100000)
        self.assertEqual(status, "READY_FOR_REVIEW")
        for stage in ("01-plan", "02-plan-review", "03-implement", "05-review"):
            request = (run / stage / "request.md").read_text()
            context = json.loads(request.split("Context:\n", 1)[1])
            labelled = request.split("\n\n# Orchestrator instructions\n", 1)[0].split("\n", 1)[1]
            unlabelled = re.sub(r"(?m)^\[R\d+\]\n", "", labelled)
            self.assertEqual(unlabelled, "## Goal\n" + text.split("\n```\n", 1)[1].strip())
            self.assertEqual((run / "00-input/task.md").read_text(), text)
            self.assertNotIn("task_chunks", context)
            self.assertLess(max(map(len, request.splitlines())), 2000)
            header = json.loads((run / stage / "agent.md").read_text().split("---")[1])
            self.assertEqual(header["permission"]["read"][str(run / "00-input/task.md")], "allow")
            self.assertNotIn(str(run / stage) + "/*", header["permission"]["read"])
            if stage != "01-plan":
                saved = str(run / "01-plan/result.json")
                self.assertNotIn("saved_results", context)
                self.assertEqual(header["permission"]["read"][saved], "allow")

    def test_large_followup_history_is_read_from_an_indexed_file(self):
        diff = "".join(f"-old line {number}\n+new line {number}\n" for number in range(2000))
        turns = [dict(run="earlier", task="Return 1", goal="Return 1", summary="Done", diff=diff)]
        history = "\n## Conversation history\n" + json.dumps(turns, indent=2)
        text = self.task.read_text() + history
        self.task.write_text(text)
        run, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW")
        history_file = run / "00-input/history.md"
        self.assertEqual((run / "00-input/task.md").read_text(), text)
        self.assertEqual([entry["text"] for entry in state["requirements"]], ["Return 2"])
        for stage in ("01-plan", "02-plan-review", "05-review"):
            request = (run / stage / "request.md").read_text()
            task = request.split("# Orchestrator instructions\n", 1)[0]
            self.assertLess(len(task.encode()), len(history.encode()) // 4)
            self.assertIn(f"They are in {history_file}. First read lines 1-7", task)
            self.assertNotIn("+new line 0", task)
            header = json.loads((run / stage / "agent.md").read_text().split("---")[1])
            self.assertEqual(header["permission"]["read"][str(history_file)], "allow")
        self.assertIn("+new line 1999", history_file.read_text())

    def test_incomplete_review_cannot_start_writer(self):
        run, status, state = self.run_mode("incomplete-review")
        self.assertEqual(status, "BLOCKED")
        self.assertNotIn("implementer", [a["stage"] for a in state["attempts"]])
        self.assertEqual(state["stages"][1]["status"], "RESULT_VALID")
        self.assertEqual(state["stages"][1]["verdict"], "BLOCKED")
        self.assertIn("Task was truncated", (run / "report.md").read_text())
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_both_reviews_keep_unverified_evidence(self):
        task = self.task.read_text()
        self.task.write_text(
            task.replace('"roots":', '"verification": ["Run the declared scenario"], "roots":', 1)
        )
        run, _status, state = self.run_mode()
        self.assertEqual(len(state["review_limits"]), 2)
        report = (run / "report.md").read_text()
        self.assertIn("Review limitations: 02-plan-review", report)
        self.assertIn("Review limitations: 05-review", report)
        request = (run / "05-review/request.md").read_text()
        context = json.loads(request.split("Context:\n", 1)[1])
        self.assertNotIn("prior_plan_review", context)
        self.assertEqual(context["diff_file"], str(run / "changes.diff"))

    def test_already_satisfied_task_needs_no_writer(self):
        task = self.task.read_text()
        self.task.write_text(
            task.replace('"roots":', '"verification": ["Run the declared scenario"], "roots":', 1)
        )
        (self.root / "hello.py").write_text("def hello():\n    return 2\n")
        run, status, state = self.run_mode("no-change")
        self.assertEqual(status, "NO_CHANGES_REQUIRED")
        self.assertEqual(state["changed_files"], [])
        self.assertEqual([a["stage"] for a in state["attempts"]], ["planner", "plan-reviewer"])
        self.assertEqual(state["checks"], [])
        self.assertEqual(len(state["review_limits"]), 1)
        self.assertIn("Review limitations: 02-plan-review", (run / "report.md").read_text())
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "taskrail",
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
        _run, status, state = self.run_mode("no-change-rejected")
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
        _run, status, state = self.run_mode("parent-twice", read_retries=0, timeout_seconds=1)
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

    def test_timeout_retry_corrects_the_plan_in_its_session(self):
        run, status, state = self.run_mode("timeout-then-invalid")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual([a["status"] for a in state["attempts"][:2]], ["TIMEOUT", "OK"])
        self.assertEqual(state["stages"][1]["session_turns"], 2)
        self.assertNotIn("FORMAT REPAIR ONLY", (run / "02-plan/request.md").read_text())
        recovery = run / "02-plan/recovery.md"
        self.assertTrue(recovery.is_file())
        first = json.loads((run / "02-plan/agent.md").read_text().split("---")[1])["permission"]
        self.assertEqual(first["read"].get(str(recovery)), "allow")

    def test_inline_wrapped_read_validates_whole_file_without_research_retry(self):
        source = self.root / "hello.py"
        source.write_text(
            "".join(f"# Setup step {n}\n" for n in range(11)) + "def hello():\n    return 2\n"
        )
        run, status, state = self.run_mode("wrapped-no-change")
        self.assertEqual(status, "NO_CHANGES_REQUIRED", state.get("summary"))
        self.assertEqual(
            [stage["stage"] for stage in state["stages"]], ["planner", "plan-reviewer"]
        )
        self.assertTrue(all(stage["session_turns"] == 1 for stage in state["stages"]))
        proof = json.loads((run / "01-plan/evidence-bindings.json").read_text())[0]
        self.assertEqual(proof["excerpt"], source.read_text().rstrip("\n"))
        self.assertEqual(proof["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(len(state["attempts"]), 2)

    def test_imported_plan_is_revalidated_under_current_contract(self):
        self.configure_mode()
        self.assertIn("return 1", (self.root / "hello.py").read_text())
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
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        self.assertEqual(
            [a["stage"] for a in state["attempts"]],
            ["planner", "plan-reviewer", "implementer", "reviewer"],
        )
        self.assertEqual(state["contract_version"], 1)
        self.assertIn("imported_draft", (run / "01-plan/request.md").read_text())

    def test_plan_read_before_write_rejection_stays_in_the_same_session(self):
        run, status, state = self.run_mode("plan-unread")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(state["stages"][0]["session_turns"], 2)
        correction = (run / "01-plan/tool-result.md").read_text()
        self.assertIn("in THIS session", correction)
        self.assertIn(str(run / "plan.md"), correction)
        self.assertEqual([stage["stage"] for stage in state["attempts"]].count("planner"), 1)

    def test_resolved_plan_read_before_write_needs_no_extra_model_turn(self):
        run, status, state = self.run_mode("plan-unread-resolved")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = state["stages"][0]
        self.assertEqual(planner["session_turns"], 1)
        self.assertEqual(planner["status"], "RESULT_VALID")
        self.assertEqual(state["stages"][1]["stage"], "plan-reviewer")
        proof = planner["warnings"][0]["recovered_by"]
        self.assertTrue(proof["read"]["call_id"].endswith("plan-read"))
        self.assertTrue(proof["call_id"].endswith("plan-write"))
        self.assertIn(
            "Recovered by a later read and successful write", (run / "report.md").read_text()
        )

    def test_permission_denied_retains_tool_input_after_operator_declines(self):
        run, status, _state = self.run_mode("denied", read_retries=0, timeout_seconds=1)
        self.assertEqual(status, "TIMEOUT")
        events = (run / "02-plan-review/events.jsonl").read_text()
        self.assertIn("/outside/skills/SKILL.md", events)
        self.assertIn("DECLINED", events)
        self.assertFalse((run / "02-plan-review/result.json").exists())

    def test_ordered_layout_has_one_result_per_stage(self):
        run, _status, state = self.run_mode()
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
                "plan.md",
                "source-packet-planner.json",
                "source-packet-plan-reviewer.json",
                "source-packet-implementer.json",
                "source-packet-reviewer.json",
            },
        )
        for record in state["stages"]:
            directory = run / record["directory"]
            self.assertTrue((directory / "result.json").exists())
            if record["mode"] == "model":
                drafted = (directory / "decision-draft.json").is_file()
                self.assertEqual(drafted, record["stage"] != "planner")
                names = {p.name for p in directory.iterdir()} - {"plan.md", "decision-draft.json"}
                self.assertEqual(
                    names,
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
        self.assertTrue((run / "01-plan/plan.md").is_file())
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
        _run, status, state = self.run_mode("many-calls")
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
        _run, status, state = self.run_mode("new")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertIsNone(state["preimages"]["project/new.py"])
        self.assertTrue((self.root / "new.py").exists())

    def test_a_provider_quota_is_retried_by_default(self):
        _run, _status, state = self.run_mode("provider-quota")
        reviews = [entry for entry in state["attempts"] if entry["stage"] == "plan-reviewer"]
        self.assertGreater(len(reviews), 1, state["attempts"])
        self.assertIn("Free usage limit reached", state["summary"])

    def test_stop_on_provider_limit_ends_the_stage_without_retries(self):
        _run, status, state = self.run_mode("provider-quota", stop_on_provider_limit=True)
        reviews = [entry for entry in state["attempts"] if entry["stage"] == "plan-reviewer"]
        self.assertEqual(len(reviews), 1, state["attempts"])
        self.assertEqual(reviews[0]["status"], "PROCESS_ERROR")
        self.assertIn("Free usage limit reached", state["summary"])
        self.assertNotEqual(status, "READY_FOR_REVIEW")

    def test_read_retry(self):
        _, status, state = self.run_mode("read-retry")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(len(state["attempts"]), 5)

    def test_invalid_plan_file_is_corrected_in_the_same_session(self):
        run, status, state = self.run_mode("invalid-once")
        self.assertEqual(status, "READY_FOR_REVIEW")
        planner = state["stages"][0]
        self.assertEqual((planner["status"], planner["session_turns"]), ("RESULT_VALID", 2))
        feedback = (run / "01-plan/tool-result.md").read_text()
        self.assertIn(
            "plan.md: line 3: Decision must be split, single, no change or blocked", feedback
        )
        self.assertIn("line 7: R1 has no outcome", feedback)
        header = json.loads((run / "01-plan/agent.md").read_text().split("---")[1])
        self.assertEqual(header["permission"]["edit"][str(run / "plan.md")], "allow")
        self.assertEqual(header["permission"]["edit"]["*"], "deny")

    def test_structured_steps_are_validated_without_model_retry(self):
        run, status, state = self.run_mode("structured-steps")
        self.assertEqual(status, "READY_FOR_REVIEW")
        self.assertEqual(len(state["attempts"]), 4)
        plan = json.loads((run / "01-plan/result.json").read_text())
        self.assertIsInstance(plan["steps"][0], dict)
        self.assertEqual(plan["steps"][0]["title"], "Return 2")
        self.assertEqual(plan["proposed_change_files"], [str(self.root / "hello.py")])
        self.assertIn("## T1: Return 2", (run / "01-plan/plan.md").read_text())

    def test_format_repair_rejected_unavailable_calls_keep_valid_conclusion(self):
        run, status, state = self.run_mode("format-unavailable")
        self.assertEqual(status, "READY_FOR_REVIEW")
        repaired = next(stage for stage in state["stages"] if stage["mode"] == "format-repair")
        self.assertEqual(repaired["stage"], "plan-reviewer")
        self.assertEqual(repaired["errors"], [])
        self.assertEqual(len(repaired["tool_errors"]), 2)
        self.assertEqual(len(repaired["warnings"]), 2)
        self.assertEqual(repaired["status"], "RESULT_VALID")
        profile = (run / repaired["directory"] / "agent.md").read_text()
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
        run, status, state = self.run_mode("review-timeout", read_retries=0)
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
        from taskrail.application.checkpoints import resume_available

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
        run, status, _state = self.run_mode("planner-timeout", read_retries=0)
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

    def test_compact_decisions_and_addressed_correction_complete_the_workflow(self):
        run, status, state = self.run_mode("compact-correction")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(state["stages"][1]["session_turns"], 2)
        saved = json.loads((run / "03-implement/result.json").read_text())
        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(saved["completed_steps"], ["T1"])
        self.assertEqual(saved["changed_files"], [str(self.root / "hello.py")])
        self.assertEqual(saved["status"], "IMPLEMENTED")
        correction = (run / "02-plan-review/tool-result.md").read_text()
        self.assertIn("FIELD_ENUM at /outcomes/0/result", correction)

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

    def allow_all_actions(self):
        text = self.task.read_text()
        self.task.write_text(text.replace('"roots":', '"auto_approve": true, "roots":', 1))

    def test_settings_verify_command_passes_and_keeps_output(self):
        self.allow_all_actions()
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
        self.allow_all_actions()
        failing = self.verify_command("import sys; print('boom'); sys.exit(3)")
        run, status, state = self.run_mode("ok", verify_commands=[failing], max_repairs=1)
        self.assertEqual(status, "CHECK_FAILED")
        self.assertEqual(len(list(run.glob("*-check"))), 2)
        self.assertIn("exit 3", state["checks"][-1]["detail"])
        self.assertIn("boom", state["checks"][-1]["detail"])

    def test_verify_command_writing_sources_stops_the_run(self):
        self.allow_all_actions()
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
        process = self.real_repository()
        header = {"roots": {"project": str(self.root)}, "isolation": "worktree"}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        return process

    def test_worktree_isolation_leaves_the_source_checkout_untouched(self):
        process = self.isolated_repository()
        self.allow_all_actions()
        probe = self.verify_command("import os; print('cwd', os.getcwd())")
        run, status, state = self.run_mode(
            "ok", worktree_base=str(self.base / "worktrees"), verify_commands=[probe]
        )
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        entry = state["worktrees"]["project"]
        worktree = Path(entry["worktree"])
        self.assertEqual(worktree, (self.base / "worktrees" / run.name / "project").resolve())
        self.assertEqual(entry["branch"], f"taskrail/{run.name}")
        self.assertEqual(state["roots"], {"project": str(worktree)})
        self.assertIn("return 1", (self.root / "hello.py").read_text())
        self.assertIn("return 2", (worktree / "hello.py").read_text())
        self.assertEqual(process.checked(self.root, ["status", "--porcelain"]), "")
        report = (run / "report.md").read_text()
        self.assertIn("## Isolated worktrees", report)
        self.assertIn("edited in isolated worktrees", report)
        log = next(run.glob("*-check/verify-01.log")).read_text()
        self.assertIn(f"cwd {worktree}", log)
        from taskrail.application.worktree_isolation import source_roots

        self.assertEqual(source_roots(state), [{"alias": "project", "path": str(self.root)}])

    def test_isolated_run_continues_in_its_worktree(self):
        self.isolated_repository()
        run, status, state = self.run_mode(
            "review-timeout", read_retries=0, worktree_base=str(self.base / "wt")
        )
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
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        with self.assertRaisesRegex(ValueError, "top-level"):
            self.run_mode("ok", worktree_base=str(self.base / "wt"))
        header["isolation"] = "copy"
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        with self.assertRaisesRegex(ValueError, "isolation"):
            configuration(self.task)

    def test_linked_worktree_ignores_other_branches_but_tracks_its_own(self):
        from taskrail.application.git_state import git_metadata

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

    def test_narration_without_a_request_continues_the_same_session(self):
        run, status, state = self.run_mode("narrate")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        review = [stage for stage in state["stages"] if stage["stage"] == "plan-reviewer"]
        self.assertEqual([stage["mode"] for stage in review], ["model"])
        self.assertEqual(review[0]["session_turns"], 2)
        prompt = (run / review[0]["directory"] / "tool-result.md").read_text()
        self.assertIn("did not follow the advertised response format", prompt)
        self.assertIn("You are the reviewer stage", prompt)
        self.assertIn(str(run / review[0]["directory"] / "request.md"), prompt)

    def test_rejected_citation_is_corrected_in_the_same_session(self):
        run, status, state = self.run_mode("bad-citation")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = [stage for stage in state["stages"] if stage["stage"] == "plan-reviewer"]
        self.assertEqual([stage["mode"] for stage in planner], ["model"])
        prompt = (run / planner[0]["directory"] / "tool-result.md").read_text()
        self.assertIn("Evidence E1", prompt)
        self.assertIn("range outside source of 3 lines", prompt)

    def test_kept_wrong_citation_gets_a_full_attempt_instead_of_a_blind_repair(self):
        run, status, state = self.run_mode("bad-citation-kept")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = [stage for stage in state["stages"] if stage["stage"] == "plan-reviewer"]
        self.assertEqual([stage["mode"] for stage in planner], ["model", "research-recovery"])
        self.assertEqual(planner[0]["session_turns"], MAX_RESULT_CORRECTIONS + 1)
        request = (run / planner[1]["directory"] / "request.md").read_text()
        self.assertIn("PREVIOUS FINAL RESPONSE WAS INVALID: Evidence E1", request)

    def test_markup_request_gets_the_json_format_in_the_same_session(self):
        run, status, state = self.run_mode("markup-request")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = [stage for stage in state["stages"] if stage["stage"] == "planner"]
        self.assertEqual([stage["mode"] for stage in planner], ["model"])
        prompt = (run / planner[0]["directory"] / "tool-result.md").read_text()
        self.assertIn('"status":"LOCAL_REQUEST"', prompt)

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
        planner = [stage for stage in state["stages"] if stage["stage"] == "plan-reviewer"]
        self.assertEqual(
            [stage["mode"] for stage in planner], ["model", "format-repair", "research-recovery"]
        )
        request = (run / planner[-1]["directory"] / "request.md").read_text()
        self.assertIn(
            "PREVIOUS FINAL RESPONSE WAS INVALID: FIELD_KEYS at /: Missing fields", request
        )

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
        with patch("taskrail.interactions.approvals.wait", side_effect=decide):
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

    def test_allow_all_actions_approves_the_change_limit_with_a_ledger(self):
        header = {"roots": {"project": str(self.root)}, "auto_approve": True}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        run, status, state = self.run_mode("ok", max_change_lines=1)
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(state["approved_change"], dict(lines=2, files=1))
        self.assertTrue(state["auto_approve"])
        ledger = [json.loads(path.read_text()) for path in run.glob("approval-*.json")]
        self.assertEqual(ledger[0]["request"]["request"]["status"], "CHANGE_LIMIT")
        self.assertTrue(ledger[0]["response"]["automatic"])

    def test_split_into_tasks_stops_after_the_reviewed_plan(self):
        header = {"roots": {"project": str(self.root)}, "decompose": True}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        run, status, state = self.run_mode("ok")
        self.assertEqual(status, "TASKS_READY", state.get("summary"))
        self.assertEqual(
            [stage["stage"] for stage in state["stages"]], ["planner", "plan-reviewer"]
        )
        self.assertIn("return 1", (self.root / "hello.py").read_text())
        plan = json.loads((run / state["results"]["plan"]).read_text())
        self.assertTrue(plan["steps"])

    def test_a_split_plan_becomes_task_runs(self):
        run, status, state = self.run_mode("two-tasks")
        self.assertEqual(status, "TASKS_READY", state.get("summary"))
        self.assertEqual(
            [stage["stage"] for stage in state["stages"]], ["planner", "plan-reviewer"]
        )
        self.assertTrue(state["auto_continue"])
        self.assertIn("return 1", (self.root / "hello.py").read_text())
        request = (run / "01-plan/request.md").read_text()
        self.assertIn("Choose split when it is several tasks", request)
        self.assertIn("implemented directly from this plan", request)
        self.assertIn("Decision: split", (run / "plan.md").read_text())

    def test_design_discussion_leaves_a_reviewed_design_document(self):
        header = {"roots": {"project": str(self.root)}, "design": True}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nDesign caching")
        run, status, state = self.run_mode("no-change")
        self.assertEqual(status, "NO_CHANGES_REQUIRED", state.get("summary"))
        self.assertEqual((run / "design.md").read_text(), "Current source already returns 2\n")
        self.assertIn("[Design document](design.md)", (run / "report.md").read_text())
        frozen = json.loads((run / "00-input/settings.json").read_text())
        self.assertIn("max_change_lines", frozen)

    def test_question_report_and_index_carry_the_reviewed_answer(self):
        header = {"roots": {"project": str(self.root)}, "read_only": True}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nWhat is returned?")
        run, status, state = self.run_mode("no-change")
        self.assertEqual(status, "NO_CHANGES_REQUIRED", state.get("summary"))
        self.assertEqual(state["answer"], "Current source already returns 2")
        report = (run / "report.md").read_text()
        self.assertIn("## Answer\n\nCurrent source already returns 2", report)
        self.assertNotIn("### Review limitations", report)
        self.assertFalse((run / "design.md").exists())

    def test_context_overflow_continues_in_a_fresh_session(self):
        run, status, state = self.run_mode("context-overflow")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = [stage for stage in state["stages"] if stage["stage"] == "planner"]
        self.assertEqual(
            [stage["status"] for stage in planner], ["CONTEXT_EXCEEDED", "RESULT_VALID"]
        )
        self.assertEqual(planner[1]["mode"], "research-recovery")
        request = (run / planner[1]["directory"] / "request.md").read_text()
        self.assertIn("EXCEEDED THE MODEL CONTEXT WINDOW", request)
        self.assertIn("The saved plan.md failed server validation", request)
        self.assertIn("Decision must be", request)
        target = json.dumps(dict(filePath=str(self.root / "hello.py")))
        self.assertIn(f"the largest were: read {target} (30000 characters)", request)
        index_end = int(re.search(r"First read lines 1-(\d+) of that file", request)[1])
        evidence = (run / planner[1]["directory"] / "recovery.md").read_text().splitlines()
        self.assertEqual(evidence[index_end : index_end + 2], ["", "## Tool result 1"])

    def test_completed_plan_survives_context_stop_and_still_receives_independent_review(self):
        run, status, state = self.run_mode("planned-overflow", read_retries=0)
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        stages = state["stages"]
        self.assertEqual(
            [stage["stage"] for stage in stages],
            ["planner", "plan-reviewer", "implementer", "check", "reviewer"],
        )
        self.assertEqual(stages[0]["status"], "RESULT_VALID")
        self.assertEqual(stages[0]["plan_recovery"]["status"], "validated")
        self.assertEqual(state["attempts"][0]["status"], "CONTEXT_EXCEEDED")
        self.assertIn("Session reached", stages[0]["errors"][0])
        self.assertEqual((run / "01-plan/plan.md").read_text(), (run / "plan.md").read_text())
        self.assertIn("return 2", (self.root / "hello.py").read_text())

    def test_context_stopped_plan_cannot_claim_unobserved_source(self):
        self.root.joinpath("unread.py").write_text("value = 2\n")
        _, status, state = self.run_mode("unobserved-planned-overflow", read_retries=0)
        self.assertEqual(status, "CONTEXT_EXCEEDED", state.get("summary"))
        self.assertEqual(len(state["stages"]), 1)
        failure = state["stages"][0]["plan_recovery"]
        self.assertEqual(failure["status"], "rejected")
        self.assertIn("no matching observed read", failure["reason"])
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_failed_read_does_not_fail_the_stage(self):
        _run, status, state = self.run_mode("failed-read")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        planner = state["stages"][0]
        self.assertEqual(planner["status"], "RESULT_VALID")
        self.assertIn("changed nothing", planner["warnings"][0]["resolution"])

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
        self.assertEqual(len(state["attempts"]), 1)
        self.assertEqual(state["stages"][0]["session_turns"], MAX_RESULT_CORRECTIONS + 1)
        self.assertEqual(len(state["attempts"][0]["validation_errors"]), MAX_RESULT_CORRECTIONS)
        self.assertIn("return 1", (self.root / "hello.py").read_text())

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
        run, status, state = self.run_mode("review-timeout", read_retries=0)
        self.assertEqual(status, "TIMEOUT")
        state["contract_version"] = 2
        (run / "run.json").write_text(json.dumps(state))
        _, status = self.continue_with_ok_model(run)
        self.assertEqual(status, "BLOCKED")
        self.assertIn(
            "Unsupported contract version", json.loads((run / "run.json").read_text())["summary"]
        )
        self.assertIn("return 2", (self.root / "hello.py").read_text())

    def test_blocked_plan_stops_without_repair_or_writes(self):
        run, status, state = self.run_mode("prose-block")
        self.assertEqual(status, "BLOCKED")
        self.assertEqual(len(state["attempts"]), 1)
        self.assertIn("Decision: blocked", (run / "plan.md").read_text())
        plan = json.loads((run / "01-plan/result.json").read_text())
        self.assertEqual(plan["blocking_gaps"], ["Mandatory local commands unavailable"])
        self.assertIn("return 1", (self.root / "hello.py").read_text())

    def test_blocked_plan_continues_with_the_operator_answer(self):
        run, status, state = self.run_mode("prose-block")
        self.assertEqual(status, "BLOCKED")
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        self.settings.write_text(json.dumps(settings))
        note = "Keep the uppercase environment variable names; plan the rest."
        _, status = execute_task(
            run / "00-input/task.md", self.settings, run_dir=run, resume=True, note=note
        )
        self.assertEqual(status, "READY_FOR_REVIEW")
        state = json.loads((run / "run.json").read_text())
        resumed = [stage for stage in state["stages"] if stage["stage"] == "planner"][-1]
        self.assertIn(note, (run / resumed["directory"] / "request.md").read_text())


if __name__ == "__main__":
    unittest.main()
