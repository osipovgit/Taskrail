import copy
import json
import tempfile
import unittest
from pathlib import Path

from countersign.infrastructure.event_summary import parse_events

PLAN = "/run/task/plan.md"
REJECTION = f"You must read file {PLAN} before overwriting it. Use the Read tool first"


class PlanWarningTests(unittest.TestCase):
    def events(self):
        operations = (("write", "error"), ("read", "completed"), ("edit", "completed"))
        events = []
        for index, (tool, status) in enumerate(operations):
            state = dict(status=status, input=dict(filePath=PLAN))
            state["error" if status == "error" else "output"] = REJECTION
            part = dict(id=f"part-{index}", callID=f"call-{index}", tool=tool, state=state)
            events.append(dict(type="tool_use", sessionID="session", part=part))
        events.extend(
            [
                dict(type="text", sessionID="session", part=dict(messageID="final", text="DONE")),
                dict(
                    type="step_finish",
                    sessionID="session",
                    part=dict(messageID="final", reason="stop"),
                ),
            ]
        )
        return events

    def parse(self, events, target=PLAN):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("\n".join(map(json.dumps, events)))
            return parse_events(path, plan_file=target)

    def test_actual_read_then_write_preserves_the_rejection_and_its_proof(self):
        for tool in ("write", "edit"):
            with self.subTest(tool=tool):
                events = self.events()
                events[2]["part"]["tool"] = tool
                result = self.parse(events)
                self.assertEqual(result["errors"], [])
                warning = result["warnings"][0]
                self.assertEqual(warning["error"], REJECTION)
                self.assertEqual(warning["recovered_by"]["read"]["event_line"], 2)
                self.assertEqual(warning["recovered_by"]["call_id"], "call-2")
                self.assertEqual(result["tool_errors"][0], warning)

    def test_missing_or_different_approved_plan_path_never_recovers_writes(self):
        for target in (None, "/run/other/plan.md", "/run/task/source.py"):
            with self.subTest(target=target):
                self.assertEqual(self.parse(self.events(), target)["errors"], [REJECTION])

    def test_actual_order_session_path_and_success_are_required(self):
        cases = []
        for index in (0, 1, 2):
            for key, value in (("sessionID", "other"), ("sessionID", None)):
                events = self.events()
                events[index][key] = value
                cases.append(events)
        for index in (1, 2):
            for change in (
                dict(input=dict(filePath="/run/other/plan.md")),
                dict(status="running"),
                dict(status="error", error="Tool execution aborted"),
            ):
                events = self.events()
                events[index]["part"]["state"].update(change)
                cases.append(events)
        events = self.events()
        cases.extend(
            [
                [events[index] for index in (1, 0, 2, 3, 4)],
                [events[index] for index in (0, 2, 1, 3, 4)],
                [events[index] for index in (0, 1, 3, 4, 2)],
                events[:3],
                [events[0], *events[3:]],
            ]
        )
        for events in cases:
            with self.subTest(events=events):
                result = self.parse(events)
                self.assertIn(REJECTION, result["errors"])
                self.assertFalse(any("recovered_by" in warning for warning in result["warnings"]))

    def test_repeated_earlier_read_cannot_prove_a_later_read(self):
        events = self.events()
        result = self.parse([events[1], events[0], *events[1:]])
        self.assertEqual(result["errors"], [REJECTION])

    def test_unrelated_and_unknown_failures_remain_errors(self):
        for error in (
            "PermissionDeniedError",
            "Must read before writing",
            "Tool execution aborted",
        ):
            events = self.events()
            extra = copy.deepcopy(events[0])
            extra["part"].update(id="other", callID="other")
            extra["part"]["state"]["error"] = error
            result = self.parse([extra, *events])
            self.assertEqual(result["errors"], [error])
            self.assertEqual(len(result["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
