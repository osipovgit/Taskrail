"""Only the current contract can enter result validation or continuation."""

import unittest

from taskrail.application import result_context
from taskrail.core import schema


class VersionTests(unittest.TestCase):
    def test_missing_and_unknown_versions_are_rejected(self):
        for version in (0, 2, None, True, "1"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "Unsupported contract version"):
                    schema.contract_version(version)
                with self.assertRaisesRegex(ValueError, "Unsupported contract version"):
                    result_context.parse({}, {}, {"contract_version": version}, {})
        with self.assertRaisesRegex(ValueError, "Unsupported contract version"):
            result_context.parse({}, {}, {}, {})
        self.assertEqual(schema.contract_version(1), 1)
