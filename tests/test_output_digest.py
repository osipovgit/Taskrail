"""Long command output reaches the model as a digest plus a file to read by windows."""

import tempfile
import unittest
from pathlib import Path

from taskrail.interactions.output_digest import summary

LINT = """WARNING Listing 3 violation(s) that are fatal
var-naming[no-role-prefix]: Variables names should start with the role name
roles/ntp/defaults/main.yml:3
var-naming[no-role-prefix]: Variables names should start with the role name
roles/ntp/defaults/main.yml:7
yaml[truthy]: Truthy value should be one of [false, true]
roles/web/tasks/main.yml:12
src/app.py:3:1: E501 line too long
Failed: 3 failure(s), 0 warning(s)
"""


class OutputDigestTests(unittest.TestCase):
    def test_lint_output_is_summarized_by_file_and_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "local-1.stdout.txt"
            output.write_text(LINT)
            digest = summary({"stdout": str(output)}).splitlines()
        self.assertEqual(
            digest[0],
            f"Digest of stdout (9 lines, {output}): lines mentioning 0 error, 2 warning, 1 fail.",
        )
        self.assertEqual(
            digest[1],
            "Files most mentioned: roles/ntp/defaults/main.yml (2), "
            "roles/web/tasks/main.yml (1), src/app.py (1)",
        )
        self.assertEqual(
            digest[2],
            "Rules most mentioned: var-naming[no-role-prefix] (2), yaml[truthy] (1), E501 (1)",
        )


if __name__ == "__main__":
    unittest.main()
