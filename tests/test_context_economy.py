"""Read-only stages never compact, and a task run gets only its own requirements."""

import unittest

from countersign.infrastructure import opencode_cli
from countersign.web import task_brief

PARENT = dict(
    requirements=[
        dict(id="R-a", text="## Goal\n- Fix lint findings in roles", kind="task"),
        dict(id="R-b", text="Keep the variable names", kind="task"),
        dict(id="R-c", text="Document the change", kind="task"),
    ]
)


class ContextEconomyTests(unittest.TestCase):
    def test_read_only_stages_fail_instead_of_compacting(self):
        self.assertNotIn("OPENCODE_DISABLE_AUTOCOMPACT", opencode_cli.environment())
        disabled = opencode_cli.environment(compact=False)
        self.assertEqual(disabled["OPENCODE_DISABLE_AUTOCOMPACT"], "true")
        self.assertEqual(disabled["OPENCODE_DISABLE_AUTOUPDATE"], "true")

    def test_a_task_run_gets_its_parent_requirements_and_results(self):
        task = dict(
            requirements=["R-a", "R-b"],
            scopes=[dict(id="R-a", scope="roles/ntp")],
            done_when=["ansible-lint roles/ntp is clean"],
            checks=["ansible-lint roles/ntp"],
        )
        self.assertEqual(
            task_brief.requirements(PARENT, task),
            "## Goal\n- Fix lint findings in roles\nOnly this assigned part: roles/ntp\n\n"
            "Keep the variable names\n\n"
            "ansible-lint roles/ntp is clean",
        )
        older = dict(requirements=[], scopes=[], done_when=[], checks=["hello returns 2"])
        self.assertEqual(task_brief.requirements(PARENT, older), "- hello returns 2")


if __name__ == "__main__":
    unittest.main()
