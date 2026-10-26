"""Intermediate Jenkins requests: the advertised contract and its validation."""

import json
from types import MappingProxyType

from countersign.core import json_response, prompt_texts, schema
from countersign.executor import jenkins_schema

STATUS = "JENKINS_REQUEST"
VERSION_FIELD = "schema_version"
STATUS_FIELD = "status"
JENKINS = "jenkins"
ENVELOPE = frozenset((VERSION_FIELD, STATUS_FIELD, JENKINS))
CONTRACT = MappingProxyType(
    {
        VERSION_FIELD: 1,
        STATUS_FIELD: STATUS,
        JENKINS: {
            "server": "configured-server-alias",
            "job": "configured-job-alias",
            "operation": "status | console | tests | build",
            "build": '"last" or a build number; "new" for a build',
            "parameters": {},
            "reason": "Purpose and what the result should show",
            "timeout_seconds": 1800,
        },
    }
)


def instructions(servers):
    """The contract and the configured servers and jobs, or nothing without Jenkins."""
    if not servers:
        return ""
    contract = json.dumps(dict(CONTRACT))
    return prompt_texts.text("routes.jenkins", contract=contract, servers=json.dumps(servers))


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
