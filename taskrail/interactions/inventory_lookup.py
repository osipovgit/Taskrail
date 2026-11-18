"""Bind a planning-time inventory lookup to a project file and a group."""

from pathlib import Path

from taskrail.application import artifacts, execution_requests, inventory_inputs, remote_catalog
from taskrail.core import json_response, prompt_texts, schema
from taskrail.executor import inventory, inventory_file
from taskrail.interactions import transcripts

STATUS = "INVENTORY_REQUEST"


def extract(text):
    payload = json_response.extract(text, schema.unique_fields)
    schema.validate(payload, schema.SCHEMAS["inventory-request"])
    return payload


def source(config, request):
    """Run trusted inventory code only in the original project checkout."""
    path = Path(request["path"])
    if path.resolve() != path:
        raise ValueError(prompt_texts.text("feedback.inventory_path"))
    for checkout, original in inventory_inputs.checkouts(config):
        if checkout in path.parents:
            trusted = original / path.relative_to(checkout)
            if str(trusted) in config.get(inventory_inputs.KEY, []):
                path = trusted
            return inventory_file.pin(inventory.selector(str(path), request["group"]))
    raise ValueError(prompt_texts.text("feedback.inventory_path"))


def discover(config, selection):
    if selection[inventory.FILENAME] in config.get(inventory_inputs.KEY, []):
        return remote_catalog.discover(selection)
    filename = Path(selection[inventory.FILENAME]).name
    if inventory.NAME_PATTERN.fullmatch(filename) and not selection.get("directory"):
        return remote_catalog.available(selection)
    return {remote_catalog.UNAVAILABLE: "feedback.inventory_source"}


def consume(actions, request):
    session = actions.session
    config = session.environment["config"]
    session.state[inventory.KEY] = {}
    artifacts.save_run(actions.run, session.state)
    try:
        selection = source(config, request)
    except (OSError, ValueError) as error:
        return refusal(
            actions,
            request,
            prompt_texts.text("feedback.rejected_request", status=STATUS, error=error),
        )
    lookup = dict(
        source=selection[inventory.FILENAME],
        resolver="ansible"
        if selection[inventory.FILENAME] in config.get(inventory_inputs.KEY, [])
        else "static-yaml",
    )
    catalog = discover(config, selection)
    if catalog.get(remote_catalog.UNAVAILABLE):
        return refusal(actions, request, remote_catalog.unavailable(catalog), lookup)
    session.state[inventory.KEY] = catalog[inventory.KEY]
    artifacts.save_run(actions.run, session.state)
    return answer(actions, request, catalog, lookup)


def refusal(actions, request, detail, lookup=None):
    """Give planner and reviewer a citable discovery failure without raw Ansible output."""
    outcome = dict(lookup or {}, status="REJECTED", detail=detail)
    return transcripts.command_snapshot(actions.folder, request, outcome, source="remote")


def answer(actions, request, catalog, lookup):
    found = dict(lookup, targets=sorted(catalog["hosts"]))
    snapshot = transcripts.command_snapshot(actions.folder, request, found, source="remote")
    rules = execution_requests.instructions(catalog, actions.run)
    return f"{snapshot}\n{rules}"
