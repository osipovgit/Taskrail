"""The quality gate stops before linting when pinned development tools drift."""

import importlib.util
import io
import unittest
from contextlib import redirect_stderr
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_tools", BASE / "tools/check_tools.py")
check_tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_tools)


class DevelopmentToolTests(unittest.TestCase):
    def run_check(self, versions):
        def version(name):
            if name not in versions:
                raise metadata.PackageNotFoundError(name)
            return versions[name]

        with (
            patch.object(check_tools.metadata, "version", side_effect=version),
            redirect_stderr(io.StringIO()) as error,
        ):
            status = check_tools.main()
        return status, error.getvalue()

    def test_every_pinned_distribution_is_checked_and_drift_is_reported_together(self):
        pinned = dict(check_tools.pins(check_tools.REQUIREMENTS.read_text()))
        self.assertTrue(
            {"ruff", "wemake-python-styleguide", "shellcheck-py", "shfmt-py"} <= set(pinned)
        )
        self.assertEqual(self.run_check(pinned), (0, ""))
        drifted = dict(pinned, ruff="0.14.0")
        drifted.pop("shellcheck-py")
        status, error = self.run_check(drifted)
        self.assertEqual(status, 1)
        self.assertIn(f"ruff: 0.14.0, pinned {pinned['ruff']}", error)
        self.assertIn("shellcheck-py: not installed", error)
        self.assertIn("-m pip install -r requirements-dev.txt", error)

    def test_comments_and_blank_lines_are_not_requirements(self):
        text = "# tools\n\nruff==1.0  # linter\nshfmt-py==2\n"
        self.assertEqual(list(check_tools.pins(text)), [("ruff", "1.0"), ("shfmt-py", "2")])


if __name__ == "__main__":
    unittest.main()
