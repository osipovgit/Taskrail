"""Keep production dependencies pointing from interfaces to the workflow and core."""

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "countersign"


class ArchitectureTests(unittest.TestCase):
    def test_core_has_no_dependency_on_interfaces_or_workflow(self):
        for path in (PACKAGE / "core").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "countersign."
                ):
                    self.assertTrue(node.module.startswith("countersign.core."), path)
