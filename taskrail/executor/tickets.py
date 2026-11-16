"""Ticket kinds: an SSH action or a Jenkins build, each with its resolved target identity."""

from datetime import datetime, timezone

from taskrail.core.schema import require
from taskrail.executor import (
    action_schema,
    hosts,
    inventory,
    jenkins_config,
    jenkins_schema,
    protocol,
)

ACTION = "action"
JENKINS = "jenkins"
SSH = "ssh"


def submission_kind(payload):
    """One request identifies its executor by its sole action field."""
    require(
        (ACTION in payload) != (JENKINS in payload) and "kind" not in payload,
        "Submit exactly one SSH action or Jenkins request",
    )
    return JENKINS if JENKINS in payload else SSH


def stored_kind(ticket):
    """A durable ticket must explicitly identify the executor allowed to run it."""
    kind = ticket.get("kind")
    require(kind in (SSH, JENKINS), "Missing or unknown executor ticket kind")
    return kind


def build_request(payload, config):
    require(submission_kind(payload) == JENKINS, "Expected a Jenkins build")
    request = jenkins_schema.validate(payload[JENKINS], config)
    require(request["operation"] == "build", "Only Jenkins builds use approval tickets")
    return request


def ssh_action(action, config):
    action_schema.validate(action)
    targets = sorted(config) if action["targets"] == "all" else action["targets"]
    if not targets or any(alias not in config for alias in targets):
        raise inventory.InventoryError("Select existing targets from the SSH inventory.")
    return dict(action, targets=targets)


def preapproved(servers, request):
    """A build of a Jenkins job whose builds root allowed in advance in its configuration."""
    job = servers[request["server"]][jenkins_config.JOBS][request["job"]]
    return request["operation"] == "build" and job.get(jenkins_config.APPROVAL) == "none"


def ssh_ticket(payload, config, identifier):
    """Bind the validated SSH action to the resolved hosts before launch."""
    protocol.label(payload["key"])
    action = ssh_action(payload["action"], config)
    shown = hosts.public(config)
    ticket = dict(
        id=identifier,
        kind=SSH,
        action=action,
        targets={alias: shown[alias] for alias in action["targets"]},
        created_at=datetime.now(timezone.utc).isoformat(),
        status="RUNNING",
        results=[],
    )
    if inventory.KEY in payload:
        ticket[inventory.KEY] = payload.get(inventory.KEY)
    return ticket
