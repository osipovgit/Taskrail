import json
import sys
import tempfile
import unittest
from pathlib import Path

from countersign.infrastructure.agent_profile import make_profile
from countersign.infrastructure.artifact_access import manifest, model_inputs, result_inputs
from countersign.infrastructure.process_watch import permission_denied_event
from countersign.infrastructure.profile_rules import permission_worktree
from countersign.infrastructure.runner import run_agent


class PermissionTests(unittest.TestCase):
    def test_current_run_results_are_readable_without_logs_or_neighbor_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run = base / "run"
            stage = run / "01-plan"
            stage.mkdir(parents=True)
            result = stage / "result.json"
            result.write_text("{}")
            (stage / "agent.md").write_text("private")
            (run / "run.json").write_text("{}")
            other = base / "other"
            other.mkdir()
            (other / "result.json").write_text("{}")
            (run / "02-plan").symlink_to(other, target_is_directory=True)
            third = run / "03-plan"
            third.mkdir()
            (third / "result.json").symlink_to(other / "result.json")
            self.assertEqual(result_inputs(run), [result])
            source = base / "role.md"
            source.write_text("role")
            access = dict(
                roots=[base / "repo"], readable=[run / "run.json", *result_inputs(run)], writable=[]
            )
            profile, _ = make_profile(source, base / "profiles", "test", access)
            policy = json.loads(profile.read_text().split("---")[1])["permission"]
            self.assertEqual(policy["external_directory"][str(run) + "/*"], "allow")
            self.assertEqual(policy["read"][str(result)], "allow")
            self.assertNotIn(str(run) + "/*", policy["read"])
            self.assertNotIn(str(stage / "agent.md"), policy["read"])
            self.assertNotIn(str(other / "result.json"), policy["read"])
            self.assertEqual(policy["edit"], {"*": "deny"})

    def test_external_files_need_parent_guard_but_exact_read(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source.md"
            source.write_text("role")
            files = [
                base / "run/00-input/task.md",
                base / "run/02-plan-review/request.md",
                base / "run/changes.diff",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("data")
            access = dict(roots=[base / "repo"], readable=files, writable=[])
            target, _ = make_profile(source, base / "profiles", "test", access)
            policy = json.loads(target.read_text().split("---")[1])["permission"]
            for path in files:
                self.assertEqual(policy["external_directory"][str(path.parent) + "/*"], "allow")
                self.assertEqual(policy["read"][str(path)], "allow")
                self.assertNotIn(str(path) + "/*", policy["read"])
                self.assertNotIn(str(path.parent) + "/*", policy["read"])
                self.assertNotIn(str(path.parent / "stderr.log"), policy["read"])
            self.assertEqual(policy["edit"], {"*": "deny"})

    def test_exact_relative_paths_across_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "qa"
            root.mkdir()
            (root / ".git").mkdir()
            source = base / "source.md"
            source.write_text("role")
            one, two = root / "build.sh", base / "jenkins" / "pipeline.groovy"
            access = dict(roots=[root, two.parent], readable=[], writable=[one, two])
            _, rules = make_profile(source, base / "profiles", "test", access)
            allowed = {
                r["pattern"] for r in rules if r["permission"] == "edit" and r["action"] == "allow"
            }
            self.assertEqual(
                allowed, {str(one), str(two), "build.sh", "../jenkins/pipeline.groovy"}
            )
            self.assertNotIn("pipeline.groovy", allowed)
            self.assertNotIn("other.sh", allowed)
            self.assertEqual(permission_worktree(root / "subdir"), root)

    def test_non_git_and_gitfile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(permission_worktree(root), Path("/"))
            (root / ".git").write_text("gitdir: elsewhere")
            with self.assertRaises(ValueError):
                permission_worktree(root)

    def test_permission_text_is_not_a_denial_event(self):
        self.assertFalse(
            permission_denied_event(
                json.dumps({"type": "text", "part": {"text": "PermissionDenied"}})
            )
        )
        self.assertFalse(permission_denied_event("not json"))

    def test_stop_before_retry_after_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prompt = root / "input.md"
            prompt.write_text("test")
            marker = root / "unwanted-retry"
            script = root / "cli.py"
            event = dict(
                type="tool_use",
                part=dict(
                    tool="edit",
                    state=dict(
                        status="error", input={"filePath": "target"}, error="PermissionDeniedError"
                    ),
                ),
            )
            script.write_text(
                "import time\nfrom pathlib import Path\nprint("
                + repr(json.dumps(event))
                + ", flush=True)\ntime.sleep(4)\nPath("
                + repr(str(marker))
                + ').write_text("retry")\n'
            )
            result = run_agent(
                dict(
                    command=[sys.executable, str(script)],
                    workspace=root,
                    agent="agent",
                    model="model",
                    prompt=prompt,
                    attempt=root / "attempt",
                    timeout=10,
                )
            )
            self.assertEqual(result["status"], "BLOCKED_PERMISSION")
            self.assertFalse(marker.exists())
            self.assertEqual(result["tool_errors"][0]["tool"], "edit")
            self.assertLess(result["elapsed_seconds"], 4)


class AccessManifestTests(unittest.TestCase):
    def test_manifest_and_profile_share_the_same_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, stage = root / "run", root / "run/01-plan"
            stage.mkdir(parents=True)
            task = run / "00-input/task.md"
            task.parent.mkdir()
            task.write_text("task")
            (stage / "request.md").write_text("request")
            (stage / "access.json").write_text("{}")
            role = root / "role.md"
            role.write_text("role")
            paths = model_inputs(run, stage)
            exposed = manifest(run, stage, {"project": str(root / "repo")})
            self.assertEqual(exposed["readable_artifacts"], list(map(str, paths)))
            access = dict(roots=[], readable=paths, writable=[])
            profile, _ = make_profile(role, root / "profiles", "test", access)
            permissions = json.loads(profile.read_text().split("---")[1])["permission"]
            for path in paths:
                self.assertEqual(permissions["read"][str(path)], "allow")
            converted, _ = make_profile(
                role, root / "profiles", "convert", access, format_only=True
            )
            self.assertNotIn("GIT_REQUEST", converted.read_text())
            converter = json.loads(converted.read_text().split("---")[1])["permission"]
            self.assertEqual(converter["read"], "deny")
            for private in (run / "evidence.json", task.parent / "git-metadata.json"):
                self.assertNotIn(str(private), permissions["read"])

    def test_executor_contracts_are_response_alternatives_not_function_tools(self):
        from countersign.application import executor_contracts
        from countersign.git.requests import extract, instructions

        git = executor_contracts.git_schema()
        payload = dict(
            schema_version=1,
            status="GIT_REQUEST",
            root="/repo",
            argv=["log", "-3"],
            reason="Inspect history",
        )
        self.assertEqual(set(git["required"]), set(payload))
        self.assertEqual(extract(json.dumps(payload)), payload)
        self.assertIn("as your entire message", instructions("planner"))
        self.assertIn("absence from your tool list is expected", instructions("planner"))
        self.assertNotIn("push", instructions("reviewer"))
        self.assertIn("A push waits for the operator's approval", instructions("implementer"))
        self.assertEqual(
            executor_contracts.ssh_schema()["properties"]["status"], {"const": "ACTION_REQUEST"}
        )
