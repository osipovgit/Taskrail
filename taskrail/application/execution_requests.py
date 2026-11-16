"""Intermediate SSH requests, separate from final stage result contracts."""

import json

from taskrail.application import delivery_confirmation, jenkins_requests, remote_catalog
from taskrail.core import delivery_record, json_response, prompt_texts, schema
from taskrail.core.files import digest
from taskrail.executor import action_schema
from taskrail.interactions.output_preview import immutable_text

SERVER = "server"
INLINE_TARGET_CHARS = 512


def instructions(catalog, run):
    """Advertise remote routes and their examples from the same catalog snapshot."""
    unavailable = catalog.get(remote_catalog.UNAVAILABLE)
    if unavailable:
        detail = remote_catalog.unavailable(catalog)
        if unavailable in {"routes.inventory.retry", "routes.ssh.inventory_error"}:
            return "{}\n{}".format(detail, prompt_texts.text("routes.inventory"))
        return "\n".join(
            filter(None, (detail, jenkins_requests.instructions(catalog.get("jenkins"))))
        )
    routes = [
        prompt_texts.text("routes.inventory") if catalog.get("inventory_lookup") else "",
        ssh_instructions(catalog.get("hosts"), run)
        if catalog.get("hosts") or not catalog.get("inventory_lookup")
        else "",
        jenkins_requests.instructions(catalog.get("jenkins")),
    ]
    return "\n\n".join(filter(None, routes))


def verify_delivery(run, config):
    """Deferred server-check phases require the authenticated delivery record."""
    if config.get("phase") != SERVER:
        return
    change = config.get("confirmed_change")
    confirmed = delivery_record.server_checks_confirmed(run, change)
    schema.require(confirmed, "Server checks require confirmed changes")
    delivery_confirmation.verify(run.parent / change)


def ssh_instructions(targets, run):
    if not targets:
        return prompt_texts.text("routes.ssh.empty")
    names = sorted(targets)
    summary = json.dumps(names)
    if len(summary) > INLINE_TARGET_CHARS:
        body = "\n".join([*names, ""])
        path = run / "00-input/remote" / f"aliases-{digest(body.encode())}.txt"
        immutable_text(path, body)
        summary = prompt_texts.text("routes.ssh.aliases", count=len(names), path=path)
    return prompt_texts.text("routes.ssh", targets=summary)


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
