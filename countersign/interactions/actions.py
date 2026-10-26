"""Route intermediate operations while retaining the original stage/session."""

import json
import re
from pathlib import Path

from countersign.core import json_response, prompt_texts, protected_paths
from countersign.git import dispatch
from countersign.interactions import (
    access,
    approval_policy,
    command_effects,
    events,
    local_request,
    request_routes,
    transcripts,
)
from countersign.interactions.clock import ApprovalPause

PUSH_NOTICE = (
    "Pushes the current commit to a remote repository. Allow all actions does not cover pushes."
)
REQUEST_NAME = re.compile(r"(?:GIT|LOCAL|ACTION|JENKINS)_REQUEST")
CORRECTIONS = "corrections"


class Actions:
    """Exact requests and personal decisions are data, not stage verdicts."""

    def __init__(self, session):
        self.session = session
        self.run = session.environment["run"]
        self.folder = session.active[0]

    def route(self, outcome):
        """Keep tool-free format repair separate from executable requests."""
        if self.session.environment["format_only"]:
            return None
        if outcome["status"] == "BLOCKED_PERMISSION":
            return self.access_action(outcome)
        if outcome["status"] != "OK":
            return None
        routed = request_routes.route(self, outcome)
        return routed or incomplete_request(self, outcome["final_text"])

    def git_action(self, outcome):
        """Use the existing policy and checkpointed Git executor."""
        session = self.session
        effect = dispatch.consume(outcome, session.active, session.state, session.environment)
        if not effect:
            return None
        session.environment.update(expected=effect[0], git_before=effect[1])
        session.state[command_effects.SOURCE_EFFECT] = effect
        path = Path(session.state["git_jobs"][-1]["output_file"])
        return transcripts.delivered(self.run, self.folder, path, path.read_text())

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

    def access_action(self, outcome):
        """Declined reads return feedback; an approved scope remains read-only."""
        calls = outcome.get("tool_errors", [])
        decision = self.approve(dict(status="ACCESS_REQUEST", calls=calls))
        answer = dict(status="DECLINED", decision=decision)
        if decision["decision"] == "allow":
            answer = access.apply_all(self.session.environment, calls)
        text = json.dumps(answer)
        events.append(self.folder, "permission", dict(calls=calls), text)
        return "{}\n{}".format(text, prompt_texts.text("feedback.access"))

    def approve(self, payload, personal=False):
        """Pause only approval time, with no deadline for the operator."""
        request = dict(stage=self.folder.name, **payload)
        environment = self.session.environment
        protected = protected_paths.patterns(environment.get("config", {}))
        scope = (environment["roots"], protected)
        with ApprovalPause(self.session):
            return approval_policy.decision(self.run, request, self.session.state, scope, personal)

    def local_result(self, payload, answer):
        """Keep command results in the public transcript and evidence ledger."""
        return transcripts.local_snapshot(self.run, self.folder, payload, answer)


def incomplete_request(actions, text):
    """Return a near-miss request or bare narration to the same session, twice per stage.

    A turn that only describes its next step, or writes a request as XML or tool-call
    markup, would otherwise go to a format repair without tools or context. A planner
    answers in plan.md, so its final text is not narration; the plan check corrects it.
    """
    context = actions.session.context
    if context[CORRECTIONS] >= request_routes.MAX_CORRECTIONS:
        return None
    if local_request.incomplete(text):
        feedback = local_request.correction(text)
    elif not_json(text) and narrated(actions, text):
        feedback = prompt_texts.text("feedback.narration", request=actions.folder / "request.md")
    else:
        return None
    context[CORRECTIONS] += 1
    events.append(actions.folder, "correction", dict(response=text), feedback)
    return feedback


def narrated(actions, text):
    """A planner answers in plan.md, so only a request written as markup counts."""
    planner = actions.session.active[1]["role"] == "planner"
    return not planner or bool(REQUEST_NAME.search(text))


def not_json(text):
    """Text without one JSON object: narration or a request written as markup.

    A single JSON object, even an invalid result, goes to validation and format repair.
    """
    if not text.strip():
        return False
    try:
        json_response.extract(text, dict)
    except ValueError:
        return True
    return False
