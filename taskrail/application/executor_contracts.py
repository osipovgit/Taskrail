"""Select the frozen release's executor response contracts for stage prompts."""

from taskrail.application import execution_requests
from taskrail.core.schema import SCHEMAS


def git_schema():
    """Git scope and role permissions remain controlled by the local executor."""
    return SCHEMAS["git-request"]


def local_schema():
    """Local argv additionally needs the operator's personal approval."""
    return SCHEMAS["local-request"]


def ssh_schema():
    """Targets, inspection scope and approval are enforced by the isolated executor."""
    return SCHEMAS["ssh-request"]


def jenkins_schema():
    """Server, job and parameter allowlists remain executor-side checks."""
    return SCHEMAS["jenkins-request"]


def for_stage(stage, run, config, catalog):
    """Only routes available in this stage are valid response alternatives."""
    catalog = execution_requests.available() if catalog is None else catalog
    alternatives = [git_schema(), local_schema()]
    if catalog.get("hosts") and execution_requests.remote_mode(run, config, stage) is not None:
        alternatives.append(ssh_schema())
    if catalog.get("jenkins"):
        alternatives.append(jenkins_schema())
    return alternatives
