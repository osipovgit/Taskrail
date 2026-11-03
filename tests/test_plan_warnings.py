import copy
import json
import tempfile
import unittest
from pathlib import Path

from taskrail.infrastructure.event_summary import parse_events
from taskrail.infrastructure.write_warnings import EDIT_MISMATCH

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

    def parse(self, events, target=PLAN, writable_files=(), notes=()):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("\n".join(map(json.dumps, events)))
            return parse_events(path, plan_file=target, writable_files=writable_files, notes=notes)

    def test_only_the_same_approved_source_can_recover_each_write(self):
        events = self.events()
        other = copy.deepcopy(events[:3])
        for event in other:
            part = event["part"]
            part["id"] += "-other"
            part["state"]["input"]["filePath"] = "/repo/other.py"
        other_error = REJECTION.replace(PLAN, "/repo/other.py")
        other[0]["part"]["state"]["error"] = other_error
        combined = [events[0], other[0], events[1], other[1], events[2], *events[3:]]
        result = self.parse(combined, None, (PLAN, "/repo/other.py"))
        self.assertEqual(result["errors"], [other_error])
        self.assertEqual(len(result["warnings"]), 1)
        combined.insert(5, other[2])
        result = self.parse(combined, None, (PLAN, "/repo/other.py"))
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["warnings"]), 2)
        result = self.parse(combined, None, (PLAN,))
        self.assertEqual(result["errors"], [other_error])

    def test_only_an_orchestrator_note_rejection_is_a_warning_without_proof(self):
        note = "/run/task/progress.md"
        rejected = json.dumps(self.events()[:1] + self.events()[3:]).replace(PLAN, note)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("\n".join(map(json.dumps, json.loads(rejected))))
            noted = parse_events(path, writable_files=(note,), notes=(note,))
            planned = parse_events(path, plan_file=note, notes=(note,))
            project = parse_events(path, writable_files=(note,), notes=(PLAN,))
        self.assertEqual(noted["errors"], [])
        self.assertIn("never evidence", noted["warnings"][0]["resolution"])
        rejection = REJECTION.replace(PLAN, note)
        self.assertEqual(planned["errors"], [rejection])
        self.assertEqual(project["errors"], [rejection])

    def test_later_unresolved_rejection_of_same_file_is_still_fatal(self):
        events = self.events()
        later = copy.deepcopy(events[0])
        later["part"]["id"] = "later-error"
        result = self.parse([*events[:3], later, *events[3:]], None, (PLAN,))
        self.assertEqual(result["errors"], [REJECTION])
        self.assertEqual(len(result["warnings"]), 1)

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

    def test_exact_edit_mismatch_requires_later_same_file_read_and_write(self):
        for prefix in ("", "Error: "):
            events = self.events()
            events[0]["part"]["tool"] = "edit"
            message = prefix + EDIT_MISMATCH
            events[0]["part"]["state"]["error"] = message
            result = self.parse(events, None, (PLAN,))
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["warnings"][0]["error"], message)
            self.assertEqual(result["warnings"][0]["recovered_by"]["read"]["event_line"], 2)
            for selected in ([0, 3, 4], [0, 1, 3, 4], [0, 2, 3, 4]):
                with self.subTest(prefix=prefix, selected=selected):
                    incomplete = [events[index] for index in selected]
                    self.assertEqual(self.parse(incomplete, None, (PLAN,))["errors"], [message])
            self.assertEqual(self.parse(events, None, ())["errors"], [message])
            for index in (1, 2):
                foreign = copy.deepcopy(events)
                foreign[index]["sessionID"] = "other"
                self.assertEqual(self.parse(foreign, None, (PLAN,))["errors"], [message])
            unknown = copy.deepcopy(events)
            unknown[0]["part"]["state"]["error"] += " Additional unknown failure"
            self.assertTrue(self.parse(unknown, None, (PLAN,))["errors"])
            events[0]["part"]["tool"] = "write"
            self.assertEqual(self.parse(events, None, (PLAN,))["errors"], [message])

    def test_repeated_mismatches_preserve_the_current_read_until_success(self):
        events = self.events()
        failure = events[0]
        failure["part"]["tool"] = "edit"
        failure["part"]["state"]["error"] = EDIT_MISMATCH
        repeated = copy.deepcopy(failure)
        repeated["part"].update(id="repeat", callID="repeat")
        for operations in (
            [events[1], failure, repeated, events[2]],
            [failure, events[1], repeated, events[2]],
        ):
            with self.subTest(operations=operations):
                result = self.parse([*operations, *events[3:]])
                self.assertEqual(result["errors"], [])
                self.assertEqual(len(result["warnings"]), 2)
                self.assertTrue(all(warning["recovered_by"] for warning in result["warnings"]))
                unresolved = self.parse([*operations[:-1], *events[3:]])
                self.assertEqual(unresolved["errors"], [EDIT_MISMATCH, EDIT_MISMATCH])

    def test_completed_write_invalidates_earlier_read_for_later_mismatch(self):
        events = self.events()
        failure = events[0]
        failure["part"]["tool"] = "edit"
        failure["part"]["state"]["error"] = EDIT_MISMATCH
        previous = copy.deepcopy(events[2])
        previous["part"].update(id="previous", callID="previous")
        result = self.parse([events[1], previous, failure, events[2], *events[3:]])
        self.assertEqual(result["errors"], [EDIT_MISMATCH])
        self.assertEqual(result["warnings"], [])

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
            "Tool execution aborted: unknown cause",
        ):
            events = self.events()
            extra = copy.deepcopy(events[0])
            extra["part"].update(id="other", callID="other")
            extra["part"]["state"]["error"] = error
            result = self.parse([extra, *events])
            self.assertEqual(result["errors"], [error])
            self.assertEqual(len(result["warnings"]), 1)

    def test_aborted_native_write_requires_a_new_read_and_successful_write(self):
        for prefix in ("", "Error: "):
            for tool in ("write", "edit"):
                events = self.events()
                message = prefix + "Tool execution aborted"
                events[0]["part"]["tool"] = tool
                events[0]["part"]["state"]["error"] = message
                with self.subTest(tool=tool, prefix=prefix):
                    result = self.parse(events, None, (PLAN,))
                    self.assertEqual(result["errors"], [])
                    self.assertEqual(result["warnings"][0]["error"], message)
                    for indices in ((1, 0, 2, 3, 4), (0, 1, 3, 4), (0, 1, 2)):
                        interrupted = [events[index] for index in indices]
                        self.assertEqual(self.parse(interrupted)["errors"], [message])
                    self.assertEqual(self.parse(events, None)["errors"], [message])

    def test_empty_aborted_edit_in_artifact_only_stage_does_not_prove_a_write(self):
        events = self.events()
        failure = events[0]["part"]
        failure["tool"] = "edit"
        failure["state"].update(input={}, error="Tool execution aborted")
        events = [events[0], *events[3:]]
        result = self.parse(events, None, (PLAN,), (PLAN,))
        self.assertEqual(result["errors"], [])
        self.assertNotIn("recovered_by", result["warnings"][0])
        self.assertIn("proves no write", result["warnings"][0]["resolution"])
        planner = self.parse(events, PLAN, (PLAN,), (PLAN,))
        self.assertEqual(planner["errors"], [])
        self.assertNotIn("recovered_by", planner["warnings"][0])
        for targets, notes in (((PLAN,), ()), ((PLAN, "/repo/source.py"), (PLAN,)), ((), (PLAN,))):
            self.assertEqual(
                self.parse(events, None, targets, notes)["errors"], ["Tool execution aborted"]
            )
        for selected in (events[:1], [*events[1:], events[0]]):
            self.assertTrue(self.parse(selected, None, (PLAN,), (PLAN,))["errors"])
        failure["state"]["input"] = dict(filePath=PLAN)
        self.assertTrue(self.parse(events, None, (PLAN,), (PLAN,))["errors"])


if __name__ == "__main__":
    unittest.main()
