"""Route intermediate operations while retaining the original stage/session."""

from pathlib import Path

from taskrail.core import prompt_texts, protected_paths, reply_frame
from taskrail.git import dispatch
from taskrail.interactions import (
    approval_policy,
    command_effects,
    request_envelope,
    request_routes,
    transcripts,
)
from taskrail.interactions.clock import ApprovalPause

PUSH_NOTICE = (
    "Pushes the current commit to a remote repository. Allow all actions does not cover pushes."
)


class Actions:
    """Exact requests and personal decisions are data, not stage verdicts."""

    def __init__(self, session):
        self.session = session
        self.run = session.environment["run"]
        self.folder = session.active[0]
        # The approval rule of the last local command, for its log entry.
        self.rule = None

    def route(self, outcome):
        """An executor request or a near-miss request; otherwise None."""
        if outcome["status"] != "OK" or reply_frame.submitted(outcome["final_text"]):
            return None
        routed = request_routes.route(self, outcome)
        return routed or incomplete_request(self, outcome) if outcome["status"] == "OK" else None

    def git_action(self, payload):
        """Use the existing policy and checkpointed Git executor."""
        session = self.session
        effect = dispatch.consume(payload, session.active, session.state, session.environment)
        session.environment.update(expected=effect[0], git_before=effect[1])
        session.state[command_effects.SOURCE_EFFECT] = effect
        path = Path(session.state["git_jobs"][-1]["output_file"])
        return transcripts.delivered(self.folder, path, path.read_text())

    def push_refusal(self, payload):
        """Feedback when the operator does not approve a push; None to run it.

        Only the implementer may push; the Git policy rejects anyone else's push.
        """
        writer = self.session.active[1]["role"] == "implementer"
        if payload["argv"][0] != "push" or not writer:
            return None
        decision = self.approve(dict(payload, notice=PUSH_NOTICE), personal=True)
        if decision["decision"] == "allow":
            return None
        reason = decision.get("alternative") or "declined."
        return prompt_texts.text("feedback.push_declined", reason=reason)

    def approve(self, payload, personal=False):
        """Pause only approval time, with no deadline for the operator."""
        request = dict(stage=self.folder.name, **payload)
        environment = self.session.environment
        protected = protected_paths.patterns(environment.get("config", {}))
        scope = (environment["roots"], protected)
        with ApprovalPause(self.session):
            return approval_policy.decision(self.run, request, self.session.state, scope, personal)

    def local_result(self, payload, answer, index=None):
        """Keep command results in the public transcript and evidence ledger."""
        return transcripts.command_snapshot(self.folder, payload, answer, index=index)


def incomplete_request(actions, outcome):
    """Return a near-miss request or bare narration to the same session, a few times in a row.

    A turn that only describes its next step, or writes a request as XML or tool-call
    markup, would otherwise fail validation and end the session. Every role answers in
    prose and its run file, so only request markup counts as narration.
    """
    feedback = request_envelope.correction(outcome["final_text"], actions.folder / "request.md")
    if feedback is None:
        return None
    return request_routes.feedback(actions, outcome, "request", feedback)
