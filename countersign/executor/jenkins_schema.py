"""Closed Jenkins request schema checked against the configured job allowlist."""

from countersign.core.schema import require
from countersign.executor import action_schema, protocol

OPERATION = "operation"
BUILD = "build"
ARGUMENTS = "parameters"
FIELDS = frozenset(("server", "job", OPERATION, BUILD, ARGUMENTS, "reason", "timeout_seconds"))
READS = frozenset(("status", "console", "tests"))


def validate(payload, servers):
    """A known server and job, an allowed operation, build reference and parameters."""
    require(isinstance(payload, dict) and set(payload) == FIELDS, "Jenkins request fields missing")
    require(payload["server"] in servers, "Unknown Jenkins server")
    jobs = servers[payload["server"]]["jobs"]
    require(payload["job"] in jobs, "Unknown Jenkins job")
    require(payload[OPERATION] in READS | {BUILD}, "Unknown Jenkins operation")
    protocol.text(payload["reason"])
    action_schema.timeout(payload["timeout_seconds"])
    check_build(payload)
    check_arguments(payload, jobs[payload["job"]][ARGUMENTS])
    return payload


def check_build(payload):
    """A new build is "new"; reads name "last" or a build number."""
    build = payload[BUILD]
    if payload[OPERATION] == BUILD:
        require(build == "new", 'A build request uses "build": "new"')
        return
    whole = isinstance(build, int) and not isinstance(build, bool)
    require(build == "last" or (whole and build > 0), 'Use "last" or a positive build number')


def check_arguments(payload, allowed):
    """Only builds take parameters, and only the configured names with text values."""
    arguments = payload[ARGUMENTS]
    require(isinstance(arguments, dict), "Parameters must be an object")
    if payload[OPERATION] != BUILD:
        require(not arguments, "Only build requests take parameters")
    require(set(arguments) <= set(allowed), "Parameter is not allowed for this job")
    for argument in arguments.values():
        require(isinstance(argument, str) and "\x00" not in argument, "Parameter values are text")
        require(len(argument) <= protocol.MAX_SCRIPT, "Parameter value is too long")
