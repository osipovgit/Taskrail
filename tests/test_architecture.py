"""Keep production dependencies pointing from interfaces to the workflow and core."""

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "countersign"


def imported_packages(package):
    """(file, imported countersign package) for every module of a package."""
    for path in (PACKAGE / package).glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("countersign."):
                yield path, node.module.split(".")[1]


class ArchitectureTests(unittest.TestCase):
    def test_core_has_no_dependency_on_interfaces_or_workflow(self):
        for path, package in imported_packages("core"):
            self.assertEqual(package, "core", path)

    def test_the_executor_service_depends_only_on_core(self):
        for path, package in imported_packages("executor"):
            self.assertIn(package, {"core", "executor"}, path)
