import json
import re
import tempfile
import unittest
from pathlib import Path

from countersign.application.history_file import INLINE_BYTES, MARKER, prompt_task

CURRENT = "```countersign-task\n{}\n```\n# Next\n\n## Goal\nReturn 3\n\n## Current turn\nRule\n"


def turn(number, diff_lines):
    return dict(
        run=f"run-{number}",
        task=f"# Turn {number}\n\n## Goal\nReturn {number}\n",
        goal=f"Return {number}\nSecond goal line",
        summary=f"Summary of turn {number}",
        conclusions={"01-plan": {"summary": "x" * 3000, "steps": []}},
        diff="".join(f"-old {number} {line}\n+new {number} {line}\n" for line in range(diff_lines)),
    )


def task_with(turns):
    return CURRENT + MARKER + json.dumps(turns, ensure_ascii=False, indent=2)


class HistoryFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        (self.run / "00-input").mkdir()
        self.file = self.run / "00-input/history.md"

    def test_small_history_stays_inline_verbatim(self):
        text = task_with([turn(1, 10)])
        self.assertLess(len(text.split(MARKER, 1)[1].encode()), INLINE_BYTES)
        self.assertEqual(prompt_task(text, self.run), text)
        self.assertFalse(self.file.exists())

    def test_large_history_is_referenced_with_a_bounded_excerpt(self):
        turns = [turn(1, 400), turn(2, 400)]
        text = task_with(turns)
        self.assertGreater(len(text.split(MARKER, 1)[1].encode()), INLINE_BYTES)
        prompt = prompt_task(text, self.run)
        current, inline = prompt.split(MARKER, 1)
        self.assertEqual(current, text.split(MARKER, 1)[0])
        self.assertLess(len(inline.encode()), INLINE_BYTES)
        self.assertIn(str(self.file), inline)
        self.assertIn("First read lines 1-8 of that file", inline)
        self.assertIn("### Run run-2", inline)
        self.assertIn("Return 2\nSecond goal line", inline)
        self.assertIn("Summary of turn 2", inline)
        self.assertNotIn("+new 2 0", inline)

    def test_index_names_the_lines_of_each_turn_and_section(self):
        sizes = (900, 30)
        prompt_task(task_with([turn(1, sizes[0]), turn(2, sizes[1])]), self.run)
        lines = self.file.read_text().split("\n")
        self.assertEqual(lines[5], "## Index")
        entries = lines[6:8]
        self.assertTrue(entries[1].startswith("2. Run run-2: lines "))
        self.assertTrue(entries[0].endswith("Goal: Return 1"))
        for number, entry in enumerate(entries, 1):
            first, last = map(int, re.search(r"lines (\d+)-(\d+)", entry).groups())
            self.assertEqual(lines[first - 1], f"## Run run-{number}")
            start, end = map(int, re.search(r"diff (\d+)-(\d+)", entry).groups())
            self.assertEqual(lines[start - 1], "### Diff")
            self.assertEqual(lines[start], f"-old {number} 0")
            self.assertEqual(end, last)
            self.assertEqual(lines[end - 1], f"+new {number} {sizes[number - 1] - 1}")
            goal = int(re.search(r"goal (\d+)-", entry)[1])
            self.assertEqual(
                lines[goal - 1 : goal + 2], ["### Goal", f"Return {number}", "Second goal line"]
            )
        self.assertLessEqual(max(map(len, lines)), 800)
        self.assertIn("x" * 500, lines)

    def test_long_excerpt_fields_are_clipped_visibly(self):
        turns = [turn(1, 400), dict(turn(2, 400), summary="s" * 5000)]
        inline = prompt_task(task_with(turns), self.run).split(MARKER, 1)[1]
        self.assertIn("[clipped; the complete text is in the history file]", inline)
        self.assertNotIn("s" * 2001, inline.replace("\n", ""))
        self.assertIn("s" * 5000, self.file.read_text().replace("\n", ""))

    def test_a_history_section_that_is_not_server_json_stays_verbatim(self):
        text = CURRENT + MARKER + "Hand-written notes\n" * 3000
        self.assertEqual(prompt_task(text, self.run), text)
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()
