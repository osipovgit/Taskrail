import unittest

from countersign.application.access_recovery import AccessRecovery


class AccessRecoveryTests(unittest.TestCase):
    def denial(self, path, tool="grep", elapsed=1):
        return dict(
            elapsed_seconds=elapsed,
            tool_errors=[dict(tool=tool, input={"path": path}, error="PermissionDeniedError")],
        )

    def test_two_distinct_denials_then_stop(self):
        recovery = AccessRecovery()
        self.assertTrue(recovery.accept(self.denial("/one"), 60))
        self.assertTrue(recovery.accept(self.denial("/two"), 60))
        self.assertFalse(recovery.accept(self.denial("/three"), 60))

    def test_repeated_request_writer_and_time_budget(self):
        recovery = AccessRecovery()
        self.assertTrue(recovery.accept(self.denial("/one"), 60))
        self.assertFalse(recovery.accept(self.denial("/one"), 60))
        self.assertFalse(AccessRecovery().accept(self.denial("/one", tool="edit"), 60))
        self.assertFalse(AccessRecovery().accept(self.denial("/one", elapsed=60), 60))
