"""Recover unambiguous read requests without repairing executable arguments."""

from taskrail.core import json_response, schema
from taskrail.git import policy


def read_request(text):
    """Allow surrounding prose only for commands validated as read-only."""
    try:
        payload = json_response.extract(text, schema.unique_fields)
    except ValueError:
        return None
    if payload.get("status") != "GIT_REQUEST":
        return None
    try:
        policy.validate(payload.get("argv"), "planner")
    except (ValueError, TypeError):
        return None
    return payload
