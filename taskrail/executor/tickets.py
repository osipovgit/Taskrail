"""Ticket kinds: an SSH action or a Jenkins build, each with the identity approval covers."""

from taskrail.core.schema import require
from taskrail.executor import action_schema, hosts, jenkins_config, jenkins_schema

JENKINS = "jenkins"
SSH = "ssh"


def kind_of(payload):
    """The kind a submission or ticket names; old tickets are SSH actions."""
    kind = payload.get("kind")
    if kind:
        return kind
    return JENKINS if JENKINS in payload else SSH


def described(payload, config):
    """(kind, validated action, identity) of a submission."""
    if kind_of(payload) == JENKINS:
        request = jenkins_schema.validate(payload[JENKINS], config)
        require(request["operation"] == "build", "Only Jenkins builds use approval tickets")
        return JENKINS, request, jenkins_config.identity(config, request)
    action = action_schema.validate(payload["action"])
    return SSH, action, ssh_identity(action, config)


def preapproved(servers, request):
    """A build of a Jenkins job whose builds root allowed in advance in its configuration."""
    job = servers[request["server"]][jenkins_config.JOBS][request["job"]]
    return request["operation"] == "build" and job.get(jenkins_config.APPROVAL) == "none"


def identity(ticket, config):
    """The current identity of a ticket's targets, compared again at approval."""
    if kind_of(ticket) == JENKINS:
        return jenkins_config.identity(config, ticket["action"])
    return ssh_identity(ticket["action"], config)


def ssh_identity(action, inventory):
    """Connection identity of each SSH target, without secrets."""
    shown = hosts.public(inventory)
    return {target: shown[target] for target in action["targets"]}
