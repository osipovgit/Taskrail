"""Jenkins requests inside one stage: UI-approved reads and root-approved builds."""

import json

from taskrail.application import execution_requests, execution_wait, jenkins_requests
from taskrail.core import prompt_texts
from taskrail.executor import client
from taskrail.interactions import events, transcripts
from taskrail.interactions.clock import ApprovalPause

READ_SECONDS = 300


def consume(actions, text):
    """Handle a JENKINS_REQUEST; any other response is left to the next route."""
    try:
        payload = jenkins_requests.extract(text)
    except ValueError as error:
        return prompt_texts.text("feedback.jenkins_rejected", error=error)
    if payload is None:
        return None
    event = events.begin(actions.folder, "jenkins", payload)
    try:
        response = routed(actions, payload)
    except BaseException:
        events.finish(actions.folder, event, prompt_texts.text("feedback.jenkins_interrupted"))
        raise
    events.finish(actions.folder, event, response)
    return response


def routed(actions, payload):
    """Validate against the executor catalog, then read or submit a build ticket."""
    authorize(actions.session)
    try:
        request = checked(payload)
    except (OSError, ValueError, LookupError) as error:
        return prompt_texts.text("feedback.jenkins_rejected", error=error)
    if request["operation"] == "build":
        return build(actions.session, request)
    return read(actions, request)


def checked(payload):
    """The request validated against the jobs the executor currently offers."""
    servers = client.request(dict(operation="catalog"))["jenkins"]
    return jenkins_requests.validate(payload, servers)


def build(session, request):
    """A build is a root-approved executor ticket, like an SSH action."""
    run = session.environment["run"]
    authorize(session)
    execution_wait.submit(run, session.active[0], request, kind="jenkins")
    with ApprovalPause(session):
        return execution_wait.resume(run, session.state)


def read(actions, request):
    """Personal approval in the UI, then one read through the executor."""
    decision = actions.approve(dict(status=jenkins_requests.STATUS, jenkins=request))
    if decision["decision"] != "allow":
        answer = json.dumps(dict(status="DECLINED", decision=decision))
        return prompt_texts.text("feedback.jenkins_declined", answer=answer)
    authorize(actions.session)
    query = dict(operation="jenkins-read", request=request)
    try:
        outcome = client.request(query, timeout=READ_SECONDS)
    except (OSError, ValueError) as error:
        outcome = dict(status="FAILED", detail=str(error))
    request = dict(status=jenkins_requests.STATUS, jenkins=request)
    return transcripts.local_snapshot(actions.run, actions.folder, request, outcome)


def authorize(session):
    """A confirmation remains current across Jenkins requests and personal read approval."""
    config = session.environment.get("config", {})
    if config.get("phase") == execution_requests.SERVER:
        execution_requests.server_authorized(session.environment["run"], config)
