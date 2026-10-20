"""Route intermediate operations while retaining the original stage/session."""

import json
import subprocess
from pathlib import Path

from countersign.git import dispatch, requests
from countersign.git.deadline import Deadline
from countersign.interactions import (
    access,
    approval_policy,
    events,
    jenkins,
    local,
    local_request,
    remote,
    transcripts,
)
from countersign.interactions.clock import ApprovalPause

MAX_CORRECTIONS = 2
NARRATION = "Your last message is neither an executor request nor a final result, so nothing was executed and the stage cannot finish. If it describes your next step, return that request now as the entire response; otherwise return the final result JSON."
MISSING_PROGRAM = "{0} is not installed on the orchestrator host. Install it, then Allow to run this exact command; or Deny."


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
            payload = local.extract(text)
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
        decision = self.approve(dict(payload, **install_notice(payload)))
        if decision["decision"] != "allow":
            return self.local_result(payload, dict(status="DECLINED", decision=decision))
        if local_request.missing_executable(payload["argv"]):
            reason = "Executable is still not installed on the orchestrator host"
            return self.local_result(payload, dict(status="REJECTED", reason=reason))
        self.session.check_sources()
        context = dict(self.session.environment, timeout=self.session.clock.remaining())
        try:
            answer = local.execute(payload, context)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            answer = dict(status="UNKNOWN", reason=str(error))
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

    A turn that only describes its next step would otherwise go to a format repair
    without tools or context, which cannot rebuild a result from narration.
    """
    context = actions.session.context
    if context["corrections"] >= MAX_CORRECTIONS:
        return None
    if local_request.incomplete(text):
        feedback = local_request.correction(text)
    elif narration(text):
        feedback = NARRATION
    else:
        return None
    context["corrections"] += 1
    events.append(actions.folder, "correction", dict(response=text), feedback)
    return feedback


def narration(text):
    """Plain text without any JSON object: the turn ended while describing a next step."""
    return bool(text.strip()) and "{" not in text


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
