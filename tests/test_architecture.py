"""Keep production dependencies pointing from interfaces to the workflow and core."""

import ast
import unittest
from graphlib import TopologicalSorter
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "taskrail"


def imported_packages(package):
    """(file, imported taskrail package) for every module of a package."""
    for path in (PACKAGE / package).glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("taskrail."):
                yield path, node.module.split(".")[1]


class ArchitectureTests(unittest.TestCase):
    def test_git_modules_have_no_import_cycles(self):
        graph = {}
        for path in (PACKAGE / "git").glob("*.py"):
            dependencies = set()
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    if node.module == "taskrail.git":
                        dependencies.update(alias.name for alias in node.names)
                    elif (node.module or "").startswith("taskrail.git."):
                        dependencies.add(node.module.split(".")[2])
                elif isinstance(node, ast.Import):
                    dependencies.update(
                        alias.name.split(".")[2]
                        for alias in node.names
                        if alias.name.startswith("taskrail.git.")
                    )
            graph[path.stem] = dependencies
        # prepare raises CycleError with the import chain when any module loops back.
        TopologicalSorter(graph).prepare()

    def test_core_has_no_dependency_on_interfaces_or_workflow(self):
        for path, package in imported_packages("core"):
            self.assertEqual(package, "core", path)

    def test_the_executor_service_depends_only_on_core(self):
        for path, package in imported_packages("executor"):
            self.assertIn(package, {"core", "executor"}, path)
