"""Readable JSON views preserve values and cannot bypass source or observation checks."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from countersign.application import evidence, source_view_json, source_views
from countersign.core import source_claims


class SourceViewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.run = self.base / "run"
        self.run.mkdir()
        self.roots = dict(repo=self.root)
        self.source = self.root / "report.json"
        self.source.write_text(
            json.dumps([dict(file=f"file-{number}.yaml") for number in range(200)])
        )

    def prepare(self):
        return source_views.prepare(self.run, self.source, self.roots)

    def test_view_preserves_source_and_has_authenticated_provenance(self):
        original = self.source.read_bytes()
        entry = self.prepare()
        target = Path(entry["path"])
        self.assertEqual(json.loads(target.read_text()), json.loads(original))
        self.assertEqual(self.source.read_bytes(), original)
        self.assertGreater(entry["lines"], 200)
        self.assertEqual(source_views.validate(self.run, target, self.roots), entry)
        self.assertEqual(self.prepare(), entry)
        self.assertEqual(evidence.validation_records(self.run), [])
        claim = dict(id="E1", path=str(target), line_start=1, line_end=2)
        with self.assertRaisesRegex(ValueError, "matching observed read"):
            source_claims.validate_claim(claim, [])

    def test_formatter_preserves_exact_scalar_lexemes(self):
        text = '{"precise":1.234567890123456789,"huge":1e9999,"zero":-0,"s":"x\\n\\u0022{}[]:,","empty":[]}'
        rendered = source_view_json.formatted(text)
        before = [match[0] for match in source_view_json.TOKENS.finditer(text)]
        after = [match[0] for match in source_view_json.TOKENS.finditer(rendered)]
        self.assertEqual(before, after)
        self.assertEqual(json.loads(rendered), json.loads(text))

    def test_ambiguous_or_unreadable_json_never_becomes_a_view(self):
        padding = '"padding":[' + ",".join('"item"' for _ in range(300)) + "]"
        rejected = [
            '{"same":1,"same":2,' + padding + "}",
            '{"same":1,"\\u0073ame":2,' + padding + "}",
            '{"number":NaN,' + padding + "}",
            '{"number":Infinity,' + padding + "}",
            '{"number":-Infinity,' + padding + "}",
            '{"value":"' + "x" * 2000 + '"}',
            '{"unfinished":[' + "1," * 1000,
            "[" * 2000 + "0" + "]" * 2000,
            "\x00" * 2000,
        ]
        for text in rejected:
            with self.subTest(text=text[:40]):
                self.source.write_text(text)
                self.assertIsNone(self.prepare())
        self.assertFalse(source_views.directory(self.run).exists())

    def test_small_sources_and_size_expansion_are_bounded(self):
        self.source.write_text('{"small": true}\n')
        self.assertIsNone(self.prepare())
        self.source.write_text(json.dumps(list(range(1000))))
        with patch.object(source_views, "MAX_BYTES", 100):
            self.assertIsNone(self.prepare())
        with patch.object(source_view_json, "MAX_BYTES", 100):
            self.assertIsNone(self.prepare())
        self.source.write_bytes(b'"' + b"\xff" * 2000 + b'"')
        self.assertIsNone(self.prepare())

    def test_changed_sources_and_views_invalidate_provenance(self):
        entry = self.prepare()
        target = Path(entry["path"])
        original = self.source.read_bytes()
        self.source.write_text("[]")
        with self.assertRaisesRegex(ValueError, "source changed"):
            source_views.validate(self.run, target, self.roots)
        self.source.write_bytes(original)
        target.write_text("[]")
        with self.assertRaisesRegex(ValueError, "content changed"):
            source_views.validate(self.run, target, self.roots)
        target.unlink()
        with self.assertRaisesRegex(ValueError, "content changed"):
            source_views.validate(self.run, target, self.roots)

    def test_views_cannot_expand_source_access_or_follow_symlinks(self):
        outside = self.base / "outside.json"
        outside.write_bytes(self.source.read_bytes())
        linked = self.root / "linked.json"
        linked.symlink_to(outside)
        protected = self.root / ".env.json"
        protected.write_bytes(self.source.read_bytes())
        metadata = self.root / ".git" / "report.json"
        metadata.parent.mkdir()
        metadata.write_bytes(self.source.read_bytes())
        for rejected in (outside, linked, protected, metadata, Path("report.json")):
            with self.subTest(path=rejected):
                self.assertIsNone(source_views.prepare(self.run, rejected, self.roots))
        entry = self.prepare()
        with self.assertRaisesRegex(ValueError, "outside approved roots"):
            source_views.validate(self.run, entry["path"], dict(other=self.base / "other"))
        target = Path(entry["path"])
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Invalid source view path"):
            source_views.validate(self.run, target, self.roots)
        self.assertIsNone(self.prepare())

    def test_unknown_artifacts_and_symlinked_storage_are_rejected(self):
        unknown = source_views.directory(self.run) / "unknown.json"
        unknown.parent.mkdir(parents=True)
        unknown.write_text("[]")
        with self.assertRaisesRegex(ValueError, "Unknown source view"):
            source_views.validate(self.run, unknown, self.roots)
        outside = self.base / "manifest.json"
        outside.write_text("{}")
        self.run.joinpath(source_views.MANIFEST).symlink_to(outside)
        self.assertIsNone(self.prepare())
        with self.assertRaisesRegex(ValueError, "Invalid source view path"):
            source_views.validate(self.run, unknown, self.roots)

    def test_malformed_provenance_is_a_validation_error(self):
        entry = self.prepare()
        target = Path(entry["path"])
        self.run.joinpath(source_views.MANIFEST).write_text(
            json.dumps({str(target): dict(path=str(target))})
        )
        with self.assertRaisesRegex(ValueError, "Invalid source view provenance"):
            source_views.validate(self.run, target, self.roots)


if __name__ == "__main__":
    unittest.main()
