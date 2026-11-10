"""plan.md: a forgiving Markdown plan that the server turns into the stored plan result."""

import tempfile
import unittest
from pathlib import Path

from taskrail.application import plan_file, project_map
from taskrail.core import source_claims
from taskrail.core.files import digest
from taskrail.core.plan_document import payload

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
    def test_annotated_shared_obligations_remain_owned_by_every_task(self):
        for outcome in ("all tasks", "all tasks (constraint)", "ALL (keep names (and values))"):
            with self.subTest(outcome=outcome):
                plan = payload(
                    PLAN.replace("done: project/README.md:12-18, roles/x.yml:3", outcome),
                    REQUIREMENTS,
                    ROOTS,
                )
                self.assertEqual(plan["coverage"][1]["outcome"], "planned")
                self.assertFalse(plan["evidence"])
                for step in plan["steps"]:
                    self.assertIn("R-bbb", step["criteria"])

    def test_self_attestation_and_unparsed_shared_outcomes_get_actionable_feedback(self):
        for outcome in (
            "done",
            "done (this plan)",
            "all tasks (constraint) T9",
            "all tasks (unclosed",
        ):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError) as rejected:
                payload(
                    PLAN.replace("done: project/README.md:12-18, roles/x.yml:3", outcome),
                    REQUIREMENTS,
                    ROOTS,
                )
            message = str(rejected.exception)
            self.assertIn("R2 needs", message)
            self.assertIn("all tasks", message)
            self.assertIn("do not mark them done by citing instructions", message)

    def test_explicit_ranges_are_evidence_but_parenthetical_prose_is_not(self):
        detail = (
            "/runs/task/00-input/git/01-plan-2.txt:7-42,43-156,157-169; "
            "` project/file with spaces.yml:2-3 ` "
            "(diff mentions v100.yaml:165-166 and 01-plan-2.txt:165-166), (final note)"
        )
        plan = payload(
            PLAN.replace("project/README.md:12-18, roles/x.yml:3", detail), REQUIREMENTS, ROOTS
        )
        self.assertEqual(
            [(entry["path"], entry["line_start"], entry["line_end"]) for entry in plan["evidence"]],
            [
                ("/runs/task/00-input/git/01-plan-2.txt", 7, 42),
                ("/runs/task/00-input/git/01-plan-2.txt", 43, 156),
                ("/runs/task/00-input/git/01-plan-2.txt", 157, 169),
                ("/repo/file with spaces.yml", 2, 3),
            ],
        )
        self.assertIn("v100.yaml:165-166", plan["coverage"][1]["explanation"])

    def test_invalid_citation_suffixes_cannot_drop_claims_silently(self):
        for detail in (
            "project/a:1,2-bad",
            "project/a:1,",
            "project/a:1;2-3",
            "project/a:1, missing",
            "project/a:1 junk project/b:2",
            "project/a:1 (unclosed",
            "project/a:1 (note), project/b:2 (unclosed",
            "project/a:1 (note),",
            "project/a:1 (note), (extra) garbage",
            "project/a:1 (note) project/b:2",
            "project/a:1 (note) (another note)",
            "`project/a`:1-bad",
            "`project/a:1`, R3 and R4 evidence above",
            "project/a:1 (note). project/b:2",
            "project/a:1. project/b:2",
        ):
            with self.subTest(detail=detail), self.assertRaisesRegex(ValueError, "cite the lines"):
                payload(
                    PLAN.replace("project/README.md:12-18, roles/x.yml:3", detail),
                    REQUIREMENTS,
                    ROOTS,
                )

    def test_each_citation_can_have_a_reason_with_both_backtick_styles(self):
        for separator in (", ", "; "):
            for citation in (
                "project/README.md:1-20",
                "`project/README.md`:1-20",
                "`project/README.md:1-20`",
            ):
                with self.subTest(separator=separator, citation=citation):
                    detail = separator.join(
                        (
                            citation + " (repo instructions)",
                            "`project/.ansible-lint`:1-15 (skip_list and warn_list (unchanged))",
                            "`project/file (with spaces);v2.yml:2-3`,5 (index mentions ignored:99).",
                        )
                    )
                    plan = payload(
                        PLAN.replace("project/README.md:12-18, roles/x.yml:3", detail),
                        REQUIREMENTS,
                        ROOTS,
                    )
                    self.assertEqual(
                        [
                            (row["path"], row["line_start"], row["line_end"])
                            for row in plan["evidence"]
                        ],
                        [
                            ("/repo/README.md", 1, 20),
                            ("/repo/.ansible-lint", 1, 15),
                            ("/repo/file (with spaces);v2.yml", 2, 3),
                            ("/repo/file (with spaces);v2.yml", 5, 5),
                        ],
                    )

    def test_a_later_annotated_citation_still_needs_observed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.txt"
            source.write_text("one\ntwo\nthree\n")
            plan = payload(
                PLAN.replace(
                    "project/README.md:12-18, roles/x.yml:3",
                    f"`{source}`:1 (observed); `{source}:3` (must not be dropped)",
                ),
                REQUIREMENTS,
                ROOTS,
            )
            records = [
                dict(
                    input=dict(filePath=str(source)),
                    output="1:one",
                    source_sha256=digest(source.read_bytes()),
                    source_event="read.jsonl",
                    event_line=1,
                )
            ]
            source_claims.validate_claim(plan["evidence"][0], records)
            with self.assertRaisesRegex(ValueError, "offset=3, limit=1"):
                source_claims.validate_claim(plan["evidence"][1], records)

    def test_sentence_period_and_single_line_ranges_preserve_exact_citations(self):
        for detail in (
            "project/a:41.",
            "project/a:41-41 (a sentence).",
            "project/a:41-41,43.",
            "project/a:41-41; project/b:5-15 (nested (reason); mention c:99).",
        ):
            with self.subTest(detail=detail):
                plan = payload(
                    PLAN.replace("project/README.md:12-18, roles/x.yml:3", detail),
                    REQUIREMENTS,
                    ROOTS,
                )
                self.assertEqual(plan["evidence"][0]["line_start"], 41)
                self.assertEqual(plan["evidence"][0]["line_end"], 41)
                multiple = "; project/b" in detail or ",43" in detail
                self.assertEqual(len(plan["evidence"]), 2 if multiple else 1)

    def test_shorthand_ranges_still_need_observed_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.txt"
            source.write_text("one\ntwo\nthree\nfour\nfive\n")
            plan = payload(
                PLAN.replace("project/README.md:12-18, roles/x.yml:3", f"{source}:1,4-5"),
                REQUIREMENTS,
                ROOTS,
            )
            records = [
                dict(
                    input=dict(filePath=str(source)),
                    output="1:one",
                    source_sha256=digest(source.read_bytes()),
                    source_event="read.jsonl",
                    event_line=1,
                )
            ]
            source_claims.validate_claim(plan["evidence"][0], records)
            with self.assertRaisesRegex(ValueError, "offset=4, limit=2"):
                source_claims.validate_claim(plan["evidence"][1], records)

    def test_invented_keys_and_prose_in_a_task_become_notes_instead_of_errors(self):
        text = PLAN.replace(
            "Notes: rename the variables",
            "Facts (cited): project/roles/ntp/tasks/main.yml:1-4 shows the module\n"
            "Notes: rename the variables",
        )
        plan = payload(text, REQUIREMENTS, ROOTS)
        notes = plan["steps"][0]["notes"]
        self.assertTrue(notes.startswith("rename the variables and keep the handlers"))
        self.assertIn("Facts (cited): project/roles/ntp/tasks/main.yml:1-4", notes)
        with self.assertRaisesRegex(ValueError, "'Approach' is not a plan key here"):
            payload("Approach: rewrite\n" + PLAN, REQUIREMENTS, ROOTS)

    def test_manifest_description_is_not_a_filename_and_invalid_read_is_reported(self):
        text = PLAN.replace(
            "Files: project/roles/ntp/tasks/main.yml, roles/ntp/defaults/main.yml (new)",
            "Files:\n- the 67 files copied from the original per 00-input/original/status.jsonl:2-69\nRead: working copies under the original checkout",
        )
        with self.assertRaises(ValueError) as rejected:
            payload(text, REQUIREMENTS, ROOTS)
        for fragment in ("Files contains prose", "Read"):
            self.assertIn(fragment, str(rejected.exception))

    def test_literal_punctuation_and_bulleted_keys_reach_the_step_once(self):
        text = PLAN.replace(
            "project/roles/ntp/tasks/main.yml, roles/ntp/defaults/main.yml (new)",
            "`project/Java [v2], config.xml`",
        ).replace("1. ansible-lint roles/ntp", "1. ansible-lint roles/ntp\n- Required checks: none")
        step = payload(text, REQUIREMENTS, ROOTS)["steps"][0]
        self.assertEqual(step["files"], ["/repo/Java [v2], config.xml"])
        self.assertEqual(step["checks"], ["ansible-lint roles/ntp"])
        self.assertEqual(step["required_checks"], [])

    def test_after_the_change_rejects_local_checks_with_a_location(self):
        with self.assertRaisesRegex(ValueError, "Move local checks"):
            payload(PLAN + "- locally rerun mvn verify\n", REQUIREMENTS, ROOTS)

    def test_files_patterns_and_prose_are_named_with_what_to_write(self):
        text = PLAN.replace(
            "Files: project/roles/ntp/tasks/main.yml, roles/ntp/defaults/main.yml (new)",
            "Files: lint fixes under roles/*/tasks/*.yaml, roles/ntp/",
            1,
        )
        with self.assertRaises(ValueError) as rejected:
            payload(text, REQUIREMENTS, ROOTS)
        self.assertIn("Files names exact file paths", str(rejected.exception))
        self.assertIn("'lint fixes under roles/*/tasks/*.yaml'", str(rejected.exception))
        self.assertIn("'roles/ntp/'", str(rejected.exception))

    def test_file_feedback_names_actual_bullet_lines_and_moves_explanations_to_notes(self):
        replacement = (
            "Files:\n- `project/site.yml`\n\n"
            "- On an isolated task branch change the role files (`roles/*/tasks/main.yaml`).\n"
            "- `roles/*/handlers/main.yaml`"
        )
        source = PLAN.replace(
            "Files: project/roles/ntp/tasks/main.yml, roles/ntp/defaults/main.yml (new)",
            replacement,
        )
        with self.assertRaises(ValueError) as rejected:
            payload(source, REQUIREMENTS, ROOTS)
        message = str(rejected.exception)
        for number, line in enumerate(source.splitlines(), 1):
            if "On an isolated task branch" in line:
                self.assertIn(f"line {number}: Files contains prose", message)
            if "handlers/main.yaml" in line:
                self.assertIn(f"line {number}: Files names exact file paths", message)
        self.assertIn("Move this entire explanation under Notes:", message)
        self.assertNotIn("'`project/site.yml`'", message)

    def test_quoted_file_spaces_and_new_marker_keep_exact_paths(self):
        source = PLAN.replace(
            "Files: project/roles/ntp/tasks/main.yml, roles/ntp/defaults/main.yml (new)",
            "Files:\n- `project/a file.yml`\n- `project/new file.yml` (new)",
        )
        plan = payload(source, REQUIREMENTS, ROOTS)
        self.assertEqual(plan["steps"][0]["files"], ["/repo/a file.yml", "/repo/new file.yml"])

    def test_after_the_change_written_as_a_task_or_as_none_lists_no_check(self):
        text = PLAN.replace("## After the change", "## T3: After the change (deferred checks)")
        text += "None. No remote checks.\nServer check: none (local task)\nJenkins check: none (no CI)\n"
        plan = payload(text, REQUIREMENTS, ROOTS)
        self.assertEqual([step["id"] for step in plan["steps"]], ["T1", "T2"])
        self.assertEqual(plan["unverified"], payload(PLAN, REQUIREMENTS, ROOTS)["unverified"])

    def test_read_ranges_keep_quoted_paths_and_ignore_paths_inside_explanations(self):
        text = PLAN.replace("Done when:", "Read: `project/a file.yml:1-2`,3-4\nDone when:", 1)
        plan = payload(text, REQUIREMENTS, ROOTS)
        self.assertEqual(plan["steps"][0]["read"], ["/repo/a file.yml:1-2", "/repo/a file.yml:3-4"])
        prose = payload(text.replace("`,3-4", "` (project/b:99)"), REQUIREMENTS, ROOTS)
        self.assertEqual(prose["steps"][0]["read"], ["/repo/a file.yml:1-2"])
        self.assertIn("(project/b:99)", prose["steps"][0]["notes"])

    def test_future_files_can_mix_with_windows_but_never_prove_completion(self):
        text = PLAN.replace(
            "Done when:",
            "Read: project/README, `project/src/App [main], v2.java` (entry point); lib.py:3-7\n"
            "- `project/report:9`:2-4, trailing-dot.\n"
            "Done when:",
            1,
        )
        step = payload(text, REQUIREMENTS, ROOTS)["steps"][0]
        self.assertEqual(
            step["read"],
            [
                "/repo/README",
                "/repo/src/App [main], v2.java",
                "/repo/lib.py:3-7",
                "/repo/report:9:2-4",
                "/repo/trailing-dot.",
            ],
        )
        self.assertIn("(entry point)", step["notes"])
        with self.assertRaisesRegex(ValueError, "cite the lines"):
            payload(
                PLAN.replace("project/README.md:12-18", "project/README.md"), REQUIREMENTS, ROOTS
            )
        for invalid in ("lib.py:bad", "lib.py:7-3", "src/*.py", "src/", "."):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Read"):
                payload(text.replace("lib.py:3-7", invalid), REQUIREMENTS, ROOTS)

    def test_a_read_hint_in_multiple_roots_must_identify_its_file(self):
        roots = dict(project="/repo", other="/second")
        text = PLAN.replace("Done when:", "Read: other/README\nDone when:", 1)
        self.assertEqual(payload(text, REQUIREMENTS, roots)["steps"][0]["read"], ["/second/README"])
        for hint in ("README", "missing/README:3"):
            with self.subTest(hint=hint), self.assertRaisesRegex(ValueError, "Read"):
                payload(text.replace("other/README", hint), REQUIREMENTS, roots)

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
            "random text\nDecision: maybe\n## Requirements\n- R1 →\n- R9 → T1\nnot a requirement\n"
            "## T1: Empty\nDepends on: T1\n"
        )
        with self.assertRaises(ValueError) as raised:
            payload(broken, REQUIREMENTS, ROOTS)
        message = str(raised.exception)
        for expected in (
            "line 1: 'random text' is not a plan key here",
            "line 2: Decision must be split, single, no change or blocked",
            "line 4: R1 has no outcome",
            "line 5: R9 is unknown",
            "line 6: expected 'R<n> → <outcome>'",
            "no line for R2, R3",
            "line 7: T1 has no Files",
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

    def test_constraints_belong_to_every_task_and_read_ranges_are_hints_not_evidence(self):
        constraint = dict(id="R-ddd", text="Keep handlers", kind="task")
        constraint["source"] = dict(field="constraints", start=0, end=13)
        requirements = [*REQUIREMENTS[:2], constraint, REQUIREMENTS[2]]
        text = (
            "Decision: split\nSummary: two roles\n## Requirements\n"
            "- R1 → T1 [ntp], T2 [web]\n- R2 → T2\n- R3 → all tasks\n- R4 → runtime\n"
            "## T1: ntp\nDepends on: none\nFiles: project/ntp.yml\n"
            "Read: project/ntp.yml:1-20, `project/defaults.yml:4`\n"
            "Done when: ntp is clean\nVerify: ansible-lint ntp.yml\n"
            "## T2: web\nDepends on: T1\nFiles: project/web.yml\nRead: <path:from-to>\n"
            "Done when: web is clean\nVerify: ansible-lint web.yml\n"
        )
        plan = payload(text, requirements, ROOTS)
        first, second = plan["steps"]
        self.assertEqual(first["criteria"], ["R-aaa", "R-ddd"])
        self.assertEqual(second["criteria"], ["R-aaa", "R-bbb", "R-ddd"])
        self.assertEqual(first["read"], ["/repo/ntp.yml:1-20", "/repo/defaults.yml:4-4"])
        self.assertEqual(second["read"], [])
        self.assertEqual(plan["evidence"], [], "Read ranges need not have been read")
        self.assertEqual(plan["unverified"], ["Playbook check passes"])
        no_change = "Decision: no change\nSummary: done\n## Requirements\n" + (
            "- R1 → done: project/a.py:1\n- R2 → done: project/a.py:1\n"
            "- R3 → all tasks\n- R4 → runtime\n"
        )
        with self.assertRaisesRegex(ValueError, "R3 → all tasks needs a task"):
            payload(no_change, requirements, ROOTS)


class PlanFileTests(unittest.TestCase):
    def test_read_only_template_can_report_an_answer_or_a_required_gap_without_a_task(self):
        requirement = dict(id="R-a", text="Explain the public API", kind="task")
        with tempfile.TemporaryDirectory() as directory:
            target = plan_file.prepare(Path(directory), [requirement], read_only=True)
            template = target.read_text()
        self.assertIn("## Answer", template)
        self.assertNotIn("## T1", template)
        for decision, outcome, status in (
            ("no change", "done: project/api.py:1", "PLAN_READY"),
            ("blocked", "gap: required API source is unavailable", "BLOCKED"),
        ):
            with self.subTest(decision=decision):
                text = template.replace("<choose a decision>", decision).replace(
                    "<outcome>", outcome
                )
                result = payload(text + "\nThe public API uses keys.", [requirement], ROOTS)
                self.assertEqual((result["status"], result["steps"]), (status, []))

    def test_the_untouched_template_names_what_to_fill_in(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            target = plan_file.prepare(run, REQUIREMENTS)
            target.write_text(target.read_text())
            plan_file.prepare(run, REQUIREMENTS[:1])
            self.assertIn("- R2 → <outcome>", target.read_text())
            self.assertIn("- R3 → runtime\n", target.read_text())
            with self.assertRaises(ValueError) as raised:
                plan_file.read_plan(run, REQUIREMENTS, ROOTS)
            message = str(raised.exception)
            self.assertIn("Decision must be", message)
            self.assertIn("R1 has no outcome", message)
            self.assertIn("T1 has no Files", message)
            source = run / "source"
            source.mkdir()
            (source / "site.yml").write_text("- name: Run the playbook check\n")
            instructions = plan_file.instructions(run, dict(project=source))
            self.assertIn(f"PROJECT MAP: {run / '00-input/project-map.md'}", instructions)
            self.assertIn(f"PLAN FILE: edit {target}", instructions)
            self.assertIn("server checks the saved file", instructions)
            self.assertIn("R6 → all tasks", instructions)

    def test_messages_name_requirements_by_label(self):
        message = plan_file.labelled("Planned requirement R-bbb has no owner", REQUIREMENTS)
        self.assertEqual(message, "Planned requirement R2 has no owner")


if __name__ == "__main__":
    unittest.main()


class ProjectMapTests(unittest.TestCase):
    def test_incidental_words_in_comments_do_not_become_planning_hints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Example.java").write_text(
                "// Historical example: audit_mode is unrelated to this task.\n"
                "public class Example {}\n"
            )
            (root / "notes.txt").write_text("Old incident involving roles/ntp and audit_mode.\n")
            shown = project_map.render(dict(project=root))
            self.assertIn("- project/Example.java (2 lines): Example", shown)
            self.assertIn("- project/notes.txt (1 lines)", shown)
            self.assertNotIn("audit_mode", shown)
            self.assertNotIn("roles/ntp", shown)
            self.assertNotIn("Requirement hints", shown)

    def test_the_map_indexes_sources_without_assigning_requirement_ownership(self):
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
            text = project_map.render(dict(project=root))
            lines = text.splitlines()
            self.assertIn(
                "- project/roles/ntp/tasks/main.yml (2 lines): Install ntp; Configure ntp_servers",
                lines,
            )
            self.assertIn("- project/image.bin (binary, large or unreadable)", lines)
            self.assertNotIn(".env", text)
            self.assertNotIn("node_modules", text)
            self.assertNotIn("Requirement hints", text)
            self.assertNotIn("R1 →", text)
            for entry in (line for line in lines if " · lines " in line):
                first, last = map(int, entry.rsplit("lines ", 1)[1].split("-"))
                self.assertTrue(lines[first - 1].startswith("## "), entry)
                self.assertTrue(lines[last - 1].strip(), entry)
