"""Authored V2 decisions become the canonical stored stage record."""

import json
from functools import partial
from pathlib import Path

from countersign.application import source_packet
from countersign.core import decision_patch, decision_result, json_response, schema
from countersign.core.files import atomic_json


def stage_decision(response, context):
    """Models author the V2 decision contract; the server derives the stored record."""
    schema.require(bool(response.strip()), "Empty final response; no JSON object received")
    payload = json_response.extract(response, schema.unique_fields)
    payload = corrected(payload, context["folder"])
    resolve = partial(resolve_reference, context)
    return decision_result.normalized(payload, context, resolve)


def corrected(payload, folder):
    """Keep the last authored draft so a correction need not repeat other decisions."""
    target = folder / "decision-draft.json"
    if "corrections" in payload:
        previous = json.loads(target.read_text()) if target.is_file() else {}
        payload = decision_patch.apply(payload, previous)
    if payload.get("schema_version") == 2:
        atomic_json(target, payload)
    return payload


def resolve_reference(context, name, start, end):
    """Absolute reads retain their normal provenance gate; handles cannot grant access."""
    if Path(name).is_absolute():
        return name
    return source_packet.resolve(name, start, end, context)
