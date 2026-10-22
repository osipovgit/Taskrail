"""plan.md: a forgiving Markdown plan that the server turns into the stored plan result."""

import tempfile
import unittest
from pathlib import Path

from countersign.application import plan_file, project_map
from countersign.core.plan_document import payload

ROOTS = {"project": "/repo"}
REQUIREMENTS = [
    dict(id="R-aaa", text="Fix lint in roles", kind="task"),
    dict(id="R-bbb", text="Keep variable names", kind="task"),
    dict(id="R-ccc", text="Playbook check passes", kind="runtime"),
]
PLAN = """# Plan
<!-- a comment
over two lines -->
**Decision:** split
Summary: two roles, ntp first

## Requirements
- R1 → T1 [roles/ntp], T2 [roles/web]
- R2 -> done: project/README.md:12-18, roles/x.yml:3
* R3: runtime: ansible-playbook --check site.yml passes

## T1: Fix `ntp`
Depends on: none
Files: project/roles/ntp/tasks/main.yml, roles/ntp/defaults/main.yml (new)
Done when:
- ansible-lint roles/ntp is clean
Verify:
1. ansible-lint roles/ntp
Notes: rename the variables
and keep the handlers

## Task 2 - Fix web
Depends on: T1
Files:
- /repo/roles/web/tasks/main.yml
Done when: ansible-lint roles/web is clean
Verify: ansible-lint roles/web

## After the change
- Jenkins check: ci/lint: BRANCH=main passes
"""


class PlanDocumentTests(unittest.TestCase):
    def test_a_forgiving_plan_becomes_the_stored_result(self):
        plan = payload(PLAN, REQUIREMENTS, ROOTS)
        self.assertEqual((plan["status"], plan["decision"]), ("PLAN_READY", "split"))
        self.assertEqual([step["id"] for step in plan["steps"]], ["T1", "T2"])
        first, second = plan["steps"]
        self.assertEqual(first["title"], "Fix `ntp`")
        self.assertEqual(
            first["files"],
            ["/repo/roles/ntp/tasks/main.yml", "/repo/roles/ntp/defaults/main.yml"],
        )
        self.assertEqual(first["notes"], "rename the variables and keep the handlers")
        self.assertEqual(first["scopes"], [dict(id="R-aaa", scope="roles/ntp")])
        self.assertEqual(
            (second["depends_on"], second["checks"]), (["T1"], ["ansible-lint roles/web"])
        )
        outcomes = [entry["outcome"] for entry in plan["coverage"]]
        self.assertEqual(outcomes, ["planned", "satisfied", "deferred"])
        self.assertEqual(
            [(entry["path"], entry["line_start"], entry["line_end"]) for entry in plan["evidence"]],
            [("/repo/README.md", 12, 18), ("/repo/roles/x.yml", 3, 3)],
        )
        self.assertEqual(
            plan["unverified"],
            [
                "ansible-playbook --check site.yml passes",
                "Jenkins check: ci/lint: BRANCH=main passes",
            ],
        )
        self.assertEqual(len(plan["proposed_change_files"]), 3)

    def test_every_problem_is_named_with_its_line(self):
        broken = (
            "Decision: maybe\n## Requirements\n- R1 →\n- R9 → T1\nnot a requirement\n"
            "## T1: Empty\nDepends on: T1\nrandom text\n"
        )
        with self.assertRaises(ValueError) as raised:
            payload(broken, REQUIREMENTS, ROOTS)
        message = str(raised.exception)
        for expected in (
            "line 1: Decision must be split, single, no change or blocked",
            "line 3: R1 has no outcome",
            "line 4: R9 is unknown",
            "line 5: expected 'R<n> → <outcome>'",
            "line 8: expected 'Key: value'",
            "no line for R2, R3",
            "line 6: T1 has no Files",
            "T1 depends on an unknown task or itself",
        ):
            self.assertIn(expected, message)

    def test_split_parts_need_distinct_scopes_and_cycles_fail(self):
        unscoped = PLAN.replace("T1 [roles/ntp], T2 [roles/web]", "T1, T2")
        with self.assertRaisesRegex(ValueError, "R1 is split between T1, T2"):
            payload(unscoped, REQUIREMENTS, ROOTS)
        cyclic = PLAN.replace("Depends on: none", "Depends on: T2")
        with self.assertRaisesRegex(ValueError, "cycle: T1 -> T2 -> T1"):
            payload(cyclic, REQUIREMENTS, ROOTS)
        single = PLAN.replace("**Decision:** split", "Decision: single")
        with self.assertRaisesRegex(ValueError, "single needs exactly one task"):
            payload(single, REQUIREMENTS, ROOTS)

    def test_a_gap_needs_a_blocked_decision_and_blocks_all_work(self):
        gap = PLAN.replace(
            "- R2 -> done: project/README.md:12-18, roles/x.yml:3", "- R2 → gap: no access"
        )
        with self.assertRaisesRegex(ValueError, "set Decision: blocked"):
            payload(gap, REQUIREMENTS, ROOTS)
        blocked = payload(
            gap.replace("**Decision:** split", "Decision: blocked"), REQUIREMENTS, ROOTS
        )
        self.assertEqual((blocked["status"], blocked["steps"]), ("BLOCKED", []))
        self.assertEqual(blocked["blocking_gaps"], ["R2: no access"])
        self.assertEqual(blocked["coverage"][0]["outcome"], "not_evaluated")

    def test_an_answer_needs_no_tasks_and_keeps_its_markdown(self):
        answer = (
            "Decision: no change\n## Requirements\n- R1 → done: project/a.py:1\n"
            "- R2 → done: project/a.py:2\n- R3 → runtime: run it\n\n## Answer\n"
            "### Context\n\nThe roles are **fine**.\n"
        )
        plan = payload(answer, REQUIREMENTS, ROOTS)
        self.assertEqual((plan["decision"], plan["steps"]), ("none", []))
        self.assertEqual(plan["summary"], "### Context\n\nThe roles are **fine**.")
        with self.assertRaisesRegex(ValueError, "no change cannot have tasks"):
            payload(answer.replace("## Answer", "## T1: x\n## Answer"), REQUIREMENTS, ROOTS)


class PlanFileTests(unittest.TestCase):
    def test_the_untouched_template_names_what_to_fill_in(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            target = plan_file.prepare(run, REQUIREMENTS)
            target.write_text(target.read_text())
            plan_file.prepare(run, REQUIREMENTS[:1])
            self.assertIn("- R3 → <outcome>", target.read_text())
            with self.assertRaises(ValueError) as raised:
                plan_file.read_plan(run, REQUIREMENTS, ROOTS)
            message = str(raised.exception)
            self.assertIn("Decision must be", message)
            self.assertIn("R1 has no outcome", message)
            self.assertIn("T1 has no Files", message)
            source = run / "source"
            source.mkdir()
            (source / "site.yml").write_text("- name: Run the playbook check\n")
            instructions = plan_file.instructions(run, dict(project=source), REQUIREMENTS)
            self.assertIn(f"PROJECT MAP: {run / '00-input/project-map.md'}", instructions)
            self.assertIn(f"the Markdown file {target}", instructions)
            self.assertIn("R<n> labels attached to the task", instructions)

    def test_messages_name_requirements_by_label(self):
        message = plan_file.labelled("Planned requirement R-bbb has no owner", REQUIREMENTS)
        self.assertEqual(message, "Planned requirement R2 has no owner")


if __name__ == "__main__":
    unittest.main()


class ProjectMapTests(unittest.TestCase):
    def test_the_map_indexes_files_landmarks_and_requirement_hints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            (root / "roles/ntp/tasks").mkdir(parents=True)
            (root / "roles/ntp/tasks/main.yml").write_text(
                "- name: Install ntp\n- name: Configure ntp_servers\n"
            )
            (root / "node_modules").mkdir()
            (root / "node_modules/skip.js").write_text("function skipped() {}\n")
            (root / ".env").write_text("SECRET=1\n")
            (root / "image.bin").write_bytes(b"\x00\x01")
            requirements = [dict(text="Rename ntp_servers in roles/ntp", kind="task")]
            text = project_map.render(dict(project=root), requirements)
            lines = text.splitlines()
            self.assertIn(
                "- project/roles/ntp/tasks/main.yml (2 lines): Install ntp; Configure ntp_servers",
                lines,
            )
            self.assertIn("- project/image.bin (binary, large or unreadable)", lines)
            self.assertNotIn(".env", text)
            self.assertNotIn("node_modules", text)
            hints = next(line for line in lines if line.startswith("R1 → "))
            self.assertIn("ntp_servers: project/roles/ntp/tasks/main.yml:2", hints)
            self.assertIn("roles/ntp: project/roles/ntp/tasks/main.yml:1", hints)
            for entry in (line for line in lines if " · lines " in line):
                first, last = map(int, entry.rsplit("lines ", 1)[1].split("-"))
                self.assertTrue(lines[first - 1].startswith("## "), entry)
                self.assertTrue(lines[last - 1].strip(), entry)
