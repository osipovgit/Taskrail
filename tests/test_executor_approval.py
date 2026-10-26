"""The root approval helper: exact digest, explicit rejection, root and terminal only."""

import io
import unittest
from unittest.mock import patch

from countersign.executor import __main__ as executor_cli
from countersign.executor import approval

ACTION = dict(
    targets=["server-a"], script="uname -a\n", files={}, reason="Inspect kernel", timeout_seconds=30
)
TICKET = dict(
    id="ticket-1",
    kind="ssh",
    action=ACTION,
    targets={"server-a": dict(hostname="192.0.2.10", port=22, username="operator")},
    status="PENDING_APPROVAL",
    digest="a" * 64,
)
JENKINS_TICKET = dict(
    TICKET,
    kind="jenkins",
    action=dict(operation="build", server="ci", job="tests", parameters=dict(BRANCH="main")),
)


class Terminal(io.StringIO):
    """Standard input that reports a terminal, as under sudo from a shell."""

    def isatty(self):
        return True


class ApprovalHelperTests(unittest.TestCase):
    def decide(self, typed, *arguments, ticket=TICKET, euid=0, stdin=None):
        """Run the helper; returns (executor requests, terminal output)."""
        requests = []

        def request(payload):
            requests.append(payload)
            return ticket if payload["operation"] == "status" else dict(id=ticket["id"])

        output = io.StringIO()
        with (
            patch("sys.argv", ["countersign-executor-approve", *arguments, ticket["id"]]),
            patch("sys.stdin", stdin or Terminal(f"{typed}\n")),
            patch("sys.stdout", output),
            patch("sys.stderr", io.StringIO()),
            patch("os.geteuid", return_value=euid),
            patch.object(approval.client, "request", side_effect=request),
        ):
            approval.main()
        return requests, output.getvalue()

    def test_the_full_digest_approves_the_displayed_script_once(self):
        requests, shown = self.decide(TICKET["digest"])
        self.assertEqual(
            requests[1], dict(operation="approve", id="ticket-1", digest=TICKET["digest"])
        )
        self.assertEqual(len(requests), 2)
        self.assertIn("Decision: APPROVE", shown)
        self.assertIn("Exact SSH stdin", shown)
        self.assertIn("uname -a", shown)

    def test_anything_but_the_exact_digest_approves_nothing(self):
        for typed in ("", "yes", TICKET["digest"][:12], TICKET["digest"].upper()):
            with self.subTest(typed=typed):
                requests, shown = self.decide(typed)
                self.assertEqual(requests, [dict(operation="status", id="ticket-1")])
                self.assertIn("Not approved.", shown)

    def test_rejection_also_requires_the_digest(self):
        requests, shown = self.decide(TICKET["digest"], "--reject")
        self.assertIn("Decision: REJECT", shown)
        self.assertEqual(
            requests[1], dict(operation="reject", id="ticket-1", digest=TICKET["digest"])
        )
        requests, _ = self.decide("", "--reject")
        self.assertEqual(len(requests), 1)

    def test_a_jenkins_build_shows_its_parameters(self):
        _, shown = self.decide("", ticket=JENKINS_TICKET)
        self.assertIn("ONE build", shown)
        self.assertIn('"BRANCH": "main"', shown)

    def test_only_root_at_a_terminal_can_decide(self):
        for euid, stdin in ((1000, None), (0, io.StringIO(f"{TICKET['digest']}\n"))):
            with self.subTest(euid=euid), self.assertRaises(SystemExit):
                self.decide(TICKET["digest"], euid=euid, stdin=stdin)

    def test_terminal_control_sequences_are_escaped(self):
        hostile = dict(TICKET, action=dict(ACTION, script="echo \x1b[2J\x1b]0;owned\x07\n"))
        _, shown = self.decide("", ticket=hostile)
        self.assertNotIn("\x1b", shown)
        self.assertIn("\\u001b[2J", shown)


class ExecutorCliTests(unittest.TestCase):
    def test_the_command_line_only_inspects(self):
        with patch.object(executor_cli.client, "request", return_value={}) as request:
            for argv in (["submit", "action.json", "--key=k"], ["approve", "ticket-1"], ["status"]):
                with (
                    self.subTest(argv=argv),
                    self.assertRaises(SystemExit),
                    patch("sys.argv", ["executor", *argv]),
                    patch("sys.stderr", io.StringIO()),
                ):
                    executor_cli.main()
            with patch("sys.argv", ["executor", "status", "ticket-1"]), patch("sys.stdout"):
                executor_cli.main()
        request.assert_called_once_with(dict(operation="status", id="ticket-1"))


if __name__ == "__main__":
    unittest.main()
