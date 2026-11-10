"""Recognize the one executor request in a final response and check its shape.

Every request type is recognized the same way: exactly one JSON object whose status
names a request. A whole Markdown fence may enclose it. Read-only Git also accepts
surrounding prose, and Git writes require a bare object. A request with a wrong shape is
rejected before anything runs, and the session is told what to fix.
"""

import json
import re
from types import MappingProxyType

from taskrail.application import execution_requests, jenkins_requests
from taskrail.core import json_response, prompt_texts, schema
from taskrail.git import requests as git_requests
from taskrail.interactions import local, local_intake, local_request

GIT = git_requests.STATUS
LOCAL = "LOCAL_REQUEST"
ACTION = "ACTION_REQUEST"
JENKINS = jenkins_requests.STATUS


REQUEST_NAME = r"(?:GIT|LOCAL|ACTION|JENKINS)_REQUEST"
REQUEST_MARKUP = re.compile(
    rf"^\s*(?:<\s*(?:{REQUEST_NAME}|request|tool_call)\b|`?{REQUEST_NAME}`?\s*[:({{]|{REQUEST_NAME}\s*$)"
    rf'|"status"\s*:\s*"{REQUEST_NAME}"|"(?:argv|cwd|action|jenkins)"\s*:',
    re.MULTILINE,
)


def correction(text, request_file):
    """Feedback for command-shaped JSON or malformed markup; ordinary prose can submit."""
    try:
        payload = json_response.extract(text, schema.unique_fields)
    except ValueError:
        if not REQUEST_MARKUP.search(text):
            return None
    else:
        if local_request.incomplete(payload):
            return local_request.correction(payload)
        if not request_fields(payload):
            return None
    return prompt_texts.text("feedback.narration", request=request_file)


def request_fields(payload):
    """Fields that distinguish an invalid executor request from an unrelated object."""
    named = payload.get("status", "")
    if not isinstance(named, str) or named.endswith("_REQUEST"):
        return True
    wrapped = payload.get("name")
    if "arguments" in payload and isinstance(wrapped, str) and wrapped in PARSERS:
        return True
    return bool({"argv", "action", "jenkins"}.intersection(payload)) or (
        "cwd" in payload and local_intake.has_command(payload)
    )


def status(text):
    """The request status of a response, or None when it is not one request object."""
    try:
        payload = json_response.extract(text, schema.unique_fields)
    except ValueError:
        return None
    if local_intake.looks_like(payload):
        return LOCAL
    named = payload.get("status")
    return named if isinstance(named, str) and named in PARSERS else None


def parsed(kind, text):
    """The validated request of a recognized response; ValueError says what is wrong."""
    if kind != GIT:
        try:
            json.loads(json_response.body(text), object_pairs_hook=schema.unique_fields)
        except (ValueError, RecursionError) as error:
            raise ValueError(prompt_texts.text("validation.request_envelope")) from error
    payload = PARSERS[kind](text)
    schema.require(payload is not None, prompt_texts.text("validation.git_envelope"))
    return payload


PARSERS = MappingProxyType(
    {
        GIT: git_requests.extract,
        LOCAL: local.extract,
        ACTION: execution_requests.extract,
        JENKINS: jenkins_requests.extract,
    }
)
