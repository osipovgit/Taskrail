"""Delivered source windows are bounded, current evidence, without model read calls."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import (
    citation_review,
    context_projection,
    evidence,
    evidence_delivery,
    recovery,
    source_delivery,
    source_packet,
    source_windows,
)
from taskrail.core import source_claims
from taskrail.infrastructure import artifact_access


class SourcePacketTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.run = self.base / "run"
        self.run.mkdir()
        self.path = self.root / "module.py"
        self.path.write_text("".join(f"value_{number} = {number}\n" for number in range(1, 101)))
        self.config = dict(roots=dict(repo=self.root), task_spec=dict(fields=[]))

    def prepare(self, reference, plan=None):
        self.config["task_spec"]["fields"] = [dict(name="entry_points", text=reference)]
        supplied = source_windows.observations(self.config, plan)
        return source_packet.prepare(self.run, "planner", self.config["roots"], supplied)

    def test_explicit_entrypoint_becomes_citable_without_a_model_read(self):
        self.assertEqual(evidence.validation_records(self.run), [])
        packet = self.prepare("repo/module.py:10-12")
        self.assertEqual(
            packet[0]["lines"],
            {"10": "value_10 = 10", "11": "value_11 = 11", "12": "value_12 = 12"},
        )
        context = dict(run=self.run, stage="planner")
        self.assertEqual(source_packet.resolve("S1", 10, 12, context), str(self.path))
        claim = dict(id="E1", path=str(self.path), line_start=10, line_end=12)
        proof = source_claims.validate_claim(claim, evidence.validation_records(self.run))
        self.assertEqual(proof["source_event"], str(source_packet.location(self.run, "planner")))
        recovery_file = self.run / "recovery.md"
        recovery.write_evidence(recovery_file, evidence.load_index(self.run, evidence.OBSERVATIONS))
        self.assertIn("value_10 = 10", recovery_file.read_text())
        claim.update(line_start=13, line_end=13)
        with self.assertRaisesRegex(ValueError, "matching observed read"):
            source_claims.validate_claim(claim, evidence.validation_records(self.run))

    def test_a_rejected_citation_brings_its_current_lines_into_the_same_session(self):
        context = dict(
            run=self.run,
            folder=self.run,
            session_id="review-session",
            roots=self.config["roots"],
            check_config={},
            deliver_lines=True,
        )
        claim = dict(id="E7", path=str(self.path), line_start=15, line_end=16)
        with self.assertRaises(ValueError) as rejected:
            citation_review.validate([claim], [], context)
        feedback = str(rejected.exception)
        self.assertIn("Evidence E7", feedback)
        self.assertIn("15: value_15 = 15\n16: value_16 = 16", feedback)
        self.assertIn("Check the claim against these lines", feedback)
        self.assertEqual(evidence_delivery.session_records(context), [])
        evidence_delivery.confirm(
            self.run,
            self.run,
            feedback,
            dict(status="OK", completed=True, sessions=["review-session"]),
        )
        records = evidence_delivery.session_records(context)
        proofs = citation_review.validate([claim], records, context)
        self.assertEqual(proofs[0]["claim_id"], "E7")
        secret = self.root / ".env"
        secret.write_text("TOKEN=hidden\n")
        hidden = dict(id="E8", path=str(secret), line_start=1, line_end=1)
        with self.assertRaises(ValueError) as withheld:
            citation_review.validate([hidden], [], context)
        self.assertNotIn("hidden", str(withheld.exception))
        self.assertIn("offset=1, limit=1", str(withheld.exception))

    def test_budget_and_range_cap_never_register_undelivered_lines(self):
        self.path.write_text("".join(f"{number}: " + "x" * 200 + "\n" for number in range(1, 101)))
        packet = self.prepare("module.py:1-100")
        rendered = json.dumps(source_delivery.public(packet), ensure_ascii=False, indent=2).encode()
        self.assertLessEqual(len(rendered), source_delivery.PACKET_BYTES)
        positions = [int(number) for entry in packet for number in entry["lines"]]
        self.assertGreater(max(positions), 1)
        self.assertLess(max(positions), source_windows.WINDOW_LINES)
        claim = dict(
            id="E1", path=str(self.path), line_start=max(positions) + 1, line_end=max(positions) + 1
        )
        with self.assertRaisesRegex(ValueError, "matching observed read"):
            source_claims.validate_claim(claim, evidence.validation_records(self.run))

    def test_entrypoints_cannot_expand_access_or_read_secrets(self):
        outside = self.base / "outside.py"
        outside.write_text("private = 1\n")
        (self.root / "link.py").symlink_to(outside)
        (self.root / ".env").write_text("TOKEN=secret\n")
        (self.root / "binary.bin").write_bytes(b"\x00\x01")
        (self.root / ".git").mkdir()
        (self.root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        rejected = [
            str(outside),
            "repo/../outside.py",
            "repo/link.py",
            "repo/.env",
            "repo/binary.bin",
            "repo/.git/HEAD",
            "module.py is the entry point",
        ]
        for reference in rejected:
            with self.subTest(reference=reference):
                self.assertEqual(self.prepare(reference), [])
        self.assertEqual(evidence.validation_records(self.run), [])

    def test_role_projection_exposes_safe_catalog_and_no_copied_verdict(self):
        self.config["check_recipes"] = dict(
            lint=dict(
                kind="local",
                phase="check",
                adapter="exit-code",
                request=dict(argv=["secret-command"]),
            )
        )
        state = dict(
            contract_version=1,
            roots=dict(repo=str(self.root)),
            requirements=[],
            checks=[],
            preimages={},
        )
        context = context_projection.request_context(
            self.config, ("planner", None, [], None), state, self.run
        )
        self.assertEqual(context["check_catalog"][0]["id"], "lint")
        self.assertNotIn("secret-command", json.dumps(context))
        plan = dict(
            decision="single",
            steps=[],
            summary="Plan",
            evidence=[],
            files_read=[],
            proposed_change_files=[str(self.path)],
        )
        context = context_projection.request_context(
            self.config, ("plan-reviewer", plan, [], None), state, self.run
        )
        self.assertNotIn("check_catalog", context)
        self.assertNotIn("files_read", context["plan"])
        self.assertEqual(context["source_packet"][0]["path"], str(self.path))
        self.assertNotIn("source_sha256", context["source_packet"][0])

    def test_plan_review_sees_selected_and_configured_checks_without_commands(self):
        recipe = dict(
            kind="local",
            phase="check",
            adapter="exit-code",
            description="Verify assigned behavior",
            request=dict(argv=["private-command"]),
        )
        self.config["check_recipes"] = {
            name: recipe for name in ("selected", "configured", "unrelated")
        }
        self.config["check_specs"] = [
            dict(
                id="fixed",
                recipe_id="configured",
                criteria=["R-fixed"],
                phase="check",
                parameters={},
            )
        ]
        selection = dict(recipe_id="selected", criteria=["R-owned"])
        plan = dict(
            decision="single", steps=[], proposed_change_files=[], check_selections=[selection]
        )
        state = dict(
            contract_version=1,
            roots=dict(repo=str(self.root)),
            requirements=[],
            checks=[],
            preimages={},
        )
        context = context_projection.request_context(
            self.config, ("plan-reviewer", plan, [], None), state, self.run
        )
        self.assertEqual(context["plan"]["check_selections"], [selection])
        self.assertEqual(
            {entry["id"] for entry in context["check_catalog"]}, {"selected", "configured"}
        )
        self.assertEqual(
            context["configured_checks"],
            [dict(id="fixed", recipe_id="configured", criteria=["R-fixed"])],
        )
        self.assertTrue(
            all(entry["description"] == recipe["description"] for entry in context["check_catalog"])
        )
        self.assertNotIn("private-command", json.dumps(context))
        self.assertNotIn("unrelated", json.dumps(context))

    def test_continuation_projection_keeps_operator_note_verbatim(self):
        note = "Keep `repo/module.py` unchanged and inspect repo/other.py."
        feedback = dict(
            operator_note=note,
            instruction="Inspect before replaying",
            previous_feedback=dict(
                operator_note="Earlier note",
                coverage=["redundant"],
                findings=[dict(file="repo/module.py")],
            ),
        )
        projected = context_projection.feedback_context(feedback, self.config["roots"])
        self.assertEqual(projected["operator_note"], note)
        self.assertEqual(projected["instruction"], feedback["instruction"])
        earlier = projected["previous_feedback"]
        self.assertEqual(earlier["operator_note"], "Earlier note")
        self.assertEqual(earlier["findings"][0]["file"], str(self.path))
        self.assertNotIn("coverage", earlier)

    def test_reviewed_child_uses_only_authenticated_task_projection(self):
        self.config.update(
            reviewed_input=True, task_text="Old task\n## Conversation history\nUnapproved goal"
        )
        self.config["task_spec"] = dict(fields=[dict(name="goal", text="Reviewed goal")])
        self.assertEqual(
            context_projection.task_text(self.config, self.run), "## Goal\nReviewed goal"
        )
        state = dict(
            contract_version=1,
            roots=dict(repo=str(self.root)),
            requirements=[],
            checks=[],
            preimages={},
        )
        context = context_projection.request_context(
            self.config, ("implementer", None, [], None), state, self.run
        )
        self.assertEqual(context["task_file"], str(self.run / "00-input/reviewed-task-spec.json"))
        inputs = self.run / "00-input"
        inputs.mkdir()
        canonical = inputs / "reviewed-task-spec.json"
        canonical.write_text(json.dumps(self.config["task_spec"]))
        inputs.joinpath("task.md").write_text(self.config["task_text"])
        inputs.joinpath("history.md").write_text("Unapproved history")
        manifest = artifact_access.manifest(self.run, self.run, self.config["roots"])
        self.assertIn(str(canonical), manifest["readable_artifacts"])
        self.assertNotIn(str(inputs / "task.md"), manifest["readable_artifacts"])
        self.assertNotIn(str(inputs / "history.md"), manifest["readable_artifacts"])


if __name__ == "__main__":
    unittest.main()
