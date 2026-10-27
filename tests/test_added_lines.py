"""The added-line scan and the repeated-failure stop of the check stage."""

import tempfile
import unittest
from pathlib import Path

from taskrail.application import added_lines, check_repeats


class AddedLineTests(unittest.TestCase):
    def scan(self, before, after, name="project/app.js"):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            run = base / "run"
            relative = name.split("/", 1)[1]
            (root / relative).parent.mkdir(parents=True)
            (root / relative).write_text(after)
            stored = None
            if before is not None:
                stored = f"00-input/preimages/{name}"
                (run / stored).parent.mkdir(parents=True)
                (run / stored).write_text(before)
            return added_lines.scan(run, dict(project=root), {name: stored})

    def test_only_added_lines_are_judged_and_secrets_are_never_echoed(self):
        key = "AKIA" + "Q" * 16
        before = f'const old = "{key}";\nconsole.log("kept");\n'
        after = before + f'const fresh = "{key}";\nconsole.log("new");\ndebugger;\n'
        records = self.scan(before, after)
        self.assertEqual([record["status"] for record in records], ["FAIL", "WARN"])
        self.assertEqual(
            records[0]["detail"],
            "Added line 3: an AWS access key; remove it; read secrets from configuration",
        )
        self.assertIn(
            "line 4: leftover debugging; line 5: leftover debugging", records[1]["detail"]
        )
        self.assertNotIn(key, str(records))

    def test_templated_and_short_values_are_not_secret_like(self):
        after = 'password: "{{vault_password}}"\ntoken: "abc"\napi_key = "s3cr3t-value-123"\n'
        records = self.scan(None, after, name="project/vars.yml")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "WARN")
        self.assertIn("line 3: a literal assigned to a secret-like name", records[0]["detail"])

    def test_a_clean_change_adds_no_record(self):
        self.assertEqual(self.scan("x = 1\n", "x = 2\nprint(x)\n", name="project/a.py"), [])


class RepeatedFailureTests(unittest.TestCase):
    def failing(self, detail, file="hello.py"):
        return [dict(file=file, status="FAIL", detail=detail)]

    def test_run_specific_output_does_not_make_failures_differ(self):
        earlier = self.failing("exit 1; evidence /r/1.json; output tail:\n1 failed in 0.53s")
        now = self.failing("exit 1; evidence /r/2.json; output tail:\n1 failed in 0.61s")
        self.assertTrue(check_repeats.repeated(dict(checks=earlier), now))

    def test_a_different_failure_a_timeout_or_review_feedback_keeps_repairing(self):
        earlier = self.failing("line 3: invalid syntax")
        self.assertFalse(check_repeats.repeated(dict(checks=earlier), self.failing("line 4")))
        timeout = self.failing("Local command timed out; inspect effects before retry")
        self.assertFalse(check_repeats.repeated(dict(checks=timeout), timeout))
        self.assertFalse(check_repeats.repeated(dict(findings=[]), earlier))
        self.assertFalse(check_repeats.repeated(None, earlier))


if __name__ == "__main__":
    unittest.main()
