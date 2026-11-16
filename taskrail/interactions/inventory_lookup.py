"""Bind a planning-time inventory lookup to a published file and a group."""

from pathlib import Path

from taskrail.application import artifacts, execution_requests, remote_catalog, workspace_paths
from taskrail.core import json_response, prompt_texts, schema
from taskrail.core.files import bounded_bytes, digest
from taskrail.executor import inventory
from taskrail.interactions import transcripts

STATUS = "INVENTORY_REQUEST"


def extract(text):
    payload = json_response.extract(text, schema.unique_fields)
    schema.validate(payload, schema.SCHEMAS["inventory-request"])
    return payload


def source(config, request):
    """Use an exact project file; the daemon independently checks its bytes."""
    path = Path(request["path"])
    if not inside_project(config, path):
        raise ValueError(prompt_texts.text("feedback.inventory_path"))
    selection = inventory.selector(path.name, request["group"])
    raw = bounded_bytes(path, inventory.MAX_BYTES)
    if raw is None:
        raise ValueError(prompt_texts.text("feedback.inventory_source"))
    return dict(selection, sha256=digest(raw))


def inside_project(config, path):
    roots = set(config["roots"].values())
    roots.update(origin for origin, _ in workspace_paths.mappings(config))
    return path.resolve() == path and bool(roots.intersection(path.parents))


def consume(actions, request):
    session = actions.session
    if session.active[1]["role"] == "implementer":
        return prompt_texts.text("feedback.ssh_refused")
    session.state[inventory.KEY] = {}
    artifacts.save_run(actions.run, session.state)
    try:
        selection = source(session.environment["config"], request)
    except (OSError, ValueError) as error:
        return prompt_texts.text("feedback.rejected_request", status=STATUS, error=error)
    catalog = remote_catalog.available(selection)
    if catalog.get(remote_catalog.UNAVAILABLE):
        return remote_catalog.unavailable(catalog)
    session.state[inventory.KEY] = selection
    artifacts.save_run(actions.run, session.state)
    return answer(actions, request, catalog)


def answer(actions, request, catalog):
    session = actions.session
    found = dict(targets=sorted(catalog["hosts"]))
    snapshot = transcripts.command_snapshot(actions.folder, request, found, source="remote")
    rules = execution_requests.instructions(
        session.environment["config"], session.active[1]["role"], actions.run, catalog
    )
    return f"{snapshot}\n{rules}"
