"""Intermediate Jenkins requests: the advertised contract and its validation."""

import json

from taskrail.core import json_response, prompt_texts, schema
from taskrail.executor import jenkins_schema

STATUS = "JENKINS_REQUEST"
VERSION_FIELD = "schema_version"
STATUS_FIELD = "status"
JENKINS = "jenkins"
ENVELOPE = frozenset((VERSION_FIELD, STATUS_FIELD, JENKINS))


def instructions(servers):
    """The contract and the configured servers and jobs, or nothing without Jenkins."""
    if not servers:
        return ""
    return prompt_texts.text("routes.jenkins", servers=json.dumps(prompt_catalog(servers)))


def extract(response):
    """One JENKINS_REQUEST object with its exact envelope, or None for any other response.

    Prose or a Markdown fence around the object is ignored; the configured job allowlist
    is checked when the request is routed.
    """
    try:
        payload = json_response.extract(response, schema.unique_fields)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get(STATUS_FIELD) != STATUS:
        return None
    schema.require(set(payload) == ENVELOPE, "Invalid Jenkins request envelope")
    schema.contract_version(payload[VERSION_FIELD])
    return payload


def validate(payload, servers):
    """The exact envelope, the contract version and the configured job allowlist."""
    schema.require(set(payload) == ENVELOPE, "Invalid envelope")
    schema.contract_version(payload[VERSION_FIELD])
    return jenkins_schema.validate(payload[JENKINS], servers)


def prompt_catalog(servers):
    """Only aliases, accepted parameters and approval mode affect model requests."""
    return {
        alias: {
            job: dict(parameters=entry["parameters"], approval=entry.get("approval", "root"))
            for job, entry in server["jobs"].items()
        }
        for alias, server in servers.items()
    }
