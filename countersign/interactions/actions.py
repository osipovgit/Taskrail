"""Route intermediate operations while retaining the original stage/session."""

import json
import re
from pathlib import Path

from countersign.application import response_format
from countersign.core import json_response
from countersign.git import dispatch, requests
from countersign.git.deadline import Deadline
from countersign.interactions import (
    access,
    approval_policy,
    events,
    jenkins,
    local_actions,
    local_request,
    remote,
    transcripts,
)
from countersign.interactions.clock import ApprovalPause
from countersign.interactions.local import extract

MAX_CORRECTIONS = 2
NARRATION = 'Your last message did not follow the advertised response format, so nothing was executed. Executor requests are JSON objects, not XML or tool-call markup. A local command is {{"schema_version": 1, "status": "LOCAL_REQUEST", "cwd": "...", "argv": ["..."], "reason": "..."}}; a Git command is {{"schema_version": 1, "status": "GIT_REQUEST", "root": "...", "argv": ["..."], "reason": "..."}}. Follow the instructions in {0}. {1}'
MISSING_PROGRAM = "{0} is not installed on the orchestrator host. Install it, then Allow to run this exact command; or Deny."
REQUEST_NAME = re.compile(r"(?:GIT|LOCAL|ACTION|JENKINS)_REQUEST")


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
        response = run_git(self, outcome)
        text = outcome["final_text"]
        if response is None:
            payload = extract(text)
            response = (
                remote.consume(self.session, text) if payload is None else run_local(self, payload)
            )
        if response is None:
            response = jenkins.consume(self, text)
        if response is None:
            response = incomplete_request(self, text)
        return response

    def git_action(self, outcome):
        """Use the existing policy and checkpointed Git executor."""
        session = self.session
        effect = dispatch.consume(outcome, session.active, session.state, session.environment)
        if not effect:
            return None
        session.environment.update(expected=effect[0], git_before=effect[1])
        session.state["git_effect"] = effect
        entry = session.state["git_jobs"][-1]
        path = Path(entry["output_file"])
        text = path.read_text()
        return transcripts.delivered(self.run, self.folder, path, text)

    def access_action(self, outcome):
        """Declined reads return feedback; an approved scope remains read-only."""
        calls = outcome.get("tool_errors", [])
        decision = self.approve(dict(status="ACCESS_REQUEST", calls=calls))
        answer = dict(status="DECLINED", decision=decision)
        if decision["decision"] == "allow":
            answer = access.apply_all(self.session.environment, calls)
        text = json.dumps(answer)
        events.append(self.folder, "permission", dict(calls=calls), text)
        return f"{text}\nDo not repeat denied calls. Continue with the user decision or permitted alternatives."

    def local_action(self, payload):
        """Review exact argv and recheck sources immediately before execution."""
        try:
            local_request.checked_request(payload, self.session.environment["roots"])
        except ValueError as error:
            return self.local_result(payload, dict(status="REJECTED", reason=str(error)))
        answer = local_actions.previous(self.run, payload)
        if answer is not None:
            return self.local_result(payload, answer)
        decision = self.approve(dict(payload, **install_notice(payload)))
        if decision["decision"] != "allow":
            answer = local_actions.execute(self.run, self.folder, payload, {}, decision)
            return self.local_result(payload, answer)
        context = dict(self.session.environment)
        context["automatic_read"] = decision.get("rule") == "read_only"
        if local_request.missing_executable(payload["argv"], context["automatic_read"]):
            reason = "Executable is still not installed on the orchestrator host"
            return self.local_result(payload, dict(status="REJECTED", reason=reason))
        self.session.check_sources()
        context["timeout"] = self.session.clock.remaining()
        answer = local_actions.execute(self.run, self.folder, payload, context, decision)
        response = self.local_result(payload, answer)
        self.session.check_sources()
        return response

    def approve(self, payload):
        """Pause only approval time, with no deadline for the operator."""
        request = dict(stage=self.folder.name, **payload)
        roots = self.session.environment["roots"]
        with ApprovalPause(self.session):
            return approval_policy.decision(self.run, request, self.session.state, roots)

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
    if context["corrections"] >= MAX_CORRECTIONS:
        return None
    if local_request.incomplete(text):
        feedback = local_request.correction(text)
    elif not_json(text) and narrated(actions, text):
        feedback = NARRATION.format(
            actions.folder / "request.md", response_format.finish(actions.session.active[1]["role"])
        )
    else:
        return None
    context["corrections"] += 1
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


def install_notice(payload):
    """Let the operator install a missing program and allow the same command."""
    program = local_request.missing_executable(payload["argv"])
    if program is None:
        return {}
    return dict(notice=MISSING_PROGRAM.format(program))


def run_local(actions, payload):
    """Keep a visible running call even during approval or process execution."""
    event = events.begin(actions.folder, "local_command", payload)
    try:
        response = actions.local_action(payload)
    except BaseException:
        events.finish(actions.folder, event, "Interrupted; inspect local effects before retrying.")
        raise
    events.finish(actions.folder, event, response)
    return response


def run_git(actions, outcome):
    """Show Git execution immediately and share the stage deadline across probes."""
    payload = requests.extract(outcome["final_text"])
    if payload is None:
        return None
    event = events.begin(actions.folder, "git", payload)
    try:
        with Deadline(actions.session.clock.remaining(), actions.run):
            response = actions.git_action(outcome)
    except BaseException:
        events.finish(
            actions.folder, event, "Interrupted; inspect the Git action journal before retrying."
        )
        raise
    events.finish(actions.folder, event, response)
    return response
