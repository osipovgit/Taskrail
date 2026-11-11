"""Ticket kinds: an SSH action or a Jenkins build, each with the identity approval covers."""

from taskrail.core.schema import require
from taskrail.executor import action_schema, hosts, jenkins_config, jenkins_schema

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


def described(payload, config):
    """(kind, validated action, identity) of a submission."""
    if submission_kind(payload) == JENKINS:
        request = jenkins_schema.validate(payload[JENKINS], config)
        require(request["operation"] == "build", "Only Jenkins builds use approval tickets")
        return JENKINS, request, jenkins_config.identity(config, request)
    action = action_schema.validate(payload[ACTION])
    return SSH, action, ssh_identity(action, config)


def preapproved(servers, request):
    """A build of a Jenkins job whose builds root allowed in advance in its configuration."""
    job = servers[request["server"]][jenkins_config.JOBS][request["job"]]
    return request["operation"] == "build" and job.get(jenkins_config.APPROVAL) == "none"


def identity(ticket, config):
    """The current identity of a ticket's targets, compared again at approval."""
    if stored_kind(ticket) == JENKINS:
        return jenkins_config.identity(config, ticket[ACTION])
    return ssh_identity(ticket[ACTION], config)


def ssh_identity(action, inventory):
    """Connection identity of each SSH target, without secrets."""
    shown = hosts.public(inventory)
    return {target: shown[target] for target in action["targets"]}
