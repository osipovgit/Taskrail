"""Intermediate SSH requests, separate from final stage result contracts."""

import json
from pathlib import Path
from types import MappingProxyType

from countersign.application import jenkins_requests
from countersign.core import delivery_record, json_response, prompt_texts, schema
from countersign.executor import action_schema, client, protocol
from countersign.interactions import remote_inspection

INSPECT = "inspect"
SERVER = "server"

CONTRACT = MappingProxyType(
    {
        "schema_version": 1,
        "status": "ACTION_REQUEST",
        "action": {
            "targets": ["configured-host-alias"],
            "script": "exact shell script to review and execute remotely",
            "files": {},
            "reason": "Purpose, expected effects and verification",
            "timeout_seconds": 300,
        },
    }
)


def instructions(config, stage, run):
    """Advertise only an installed executor and what it offers; expose no credentials."""
    if not Path(protocol.SOCKET).exists():
        return prompt_texts.text("routes.ssh.unavailable")
    try:
        catalog = client.request({"operation": "catalog"})
    except (OSError, ValueError):
        return prompt_texts.text("routes.ssh.unreachable")
    routes = [
        ssh_instructions(catalog.get("hosts"), server_scope(config, stage, run)),
        jenkins_requests.instructions(catalog.get("jenkins")),
    ]
    return "\n\n".join(filter(None, routes))


def server_scope(config, stage, run):
    """What server actions may do in this stage; None when they are unavailable."""
    mode = remote_mode(run, config, stage)
    if mode is None:
        return None
    if mode == SERVER:
        return prompt_texts.text("routes.ssh.server")
    return prompt_texts.text("routes.ssh.inspect", commands=remote_inspection.listed())


def remote_mode(run, config, role):
    """What the SSH route allows, decided by the server, never by the model.

    server: this is the server check run of a change the operator confirmed; inspect:
    one read-only command per action; None: no server actions while implementing.
    """
    if role == "implementer":
        return None
    change = config.get("confirmed_change")
    if config.get("phase") == SERVER and delivery_record.server_checks_confirmed(run, change):
        return SERVER
    return INSPECT


def ssh_instructions(targets, scope):
    """The ACTION_REQUEST contract and the configured targets, or nothing without targets."""
    if not targets:
        return ""
    if scope is None:
        return prompt_texts.text("routes.ssh.implementing")
    return prompt_texts.text(
        "routes.ssh",
        contract=json.dumps(dict(CONTRACT)),
        scope=scope,
        targets=json.dumps(targets),
    )


def extract(response):
    """The validated action of one ACTION_REQUEST object; prose around it is ignored."""
    try:
        payload = json_response.extract(response, schema.unique_fields)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("status") != "ACTION_REQUEST":
        return None
    fields = {"schema_version", "status", "action"}
    if set(payload) != fields:
        raise ValueError("Invalid action request contract")
    schema.contract_version(payload["schema_version"])
    return action_schema.validate(payload["action"])
