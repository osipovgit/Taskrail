"""Validate exact server-owned Jenkins recipes before inventory resolution."""

from taskrail.core.schema import require
from taskrail.executor import action_schema, protocol

SERVER = "server"


def validate_jenkins(request):
    """Inventory and credential checks still happen in the isolated executor."""
    fields = {"server", "job", "operation", "build", "parameters", "reason", "timeout_seconds"}
    require(isinstance(request, dict) and set(request) == fields, "Invalid Jenkins recipe")
    protocol.label(request[SERVER])
    protocol.label(request["job"])
    require(
        request["operation"] == "build" and request["build"] == "new",
        "A Jenkins recipe starts one build",
    )
    check_arguments(request["parameters"])
    protocol.text(request["reason"])
    action_schema.timeout(request["timeout_seconds"])


def check_arguments(arguments):
    """The server template fixes exact string parameters; models cannot override them."""
    require(isinstance(arguments, dict), "Jenkins parameters must be an object")
    for name, argument in arguments.items():
        protocol.label(name)
        require(isinstance(argument, str), "Jenkins parameter values must be text")
