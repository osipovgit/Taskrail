"""Recognize the one executor request in a final response and check its shape.

Every request type is recognized the same way: exactly one JSON object whose status
names a request, with any prose or Markdown fence around it ignored. Only a Git request
that can change state must be the entire response. A request with a wrong shape is
rejected before anything runs, and the session is told what to fix.
"""

from types import MappingProxyType

from taskrail.application import execution_requests, jenkins_requests
from taskrail.core import json_response, prompt_texts, schema
from taskrail.git import requests as git_requests
from taskrail.interactions import local

GIT = git_requests.STATUS
LOCAL = "LOCAL_REQUEST"
ACTION = "ACTION_REQUEST"
JENKINS = jenkins_requests.STATUS


def status(text):
    """The request status of a response, or None when it is not one request object."""
    try:
        payload = json_response.extract(text, schema.unique_fields)
    except ValueError:
        return None
    named = payload.get("status")
    return named if named in PARSERS else None


def parsed(kind, text):
    """The validated request of a recognized response; ValueError says what is wrong."""
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
