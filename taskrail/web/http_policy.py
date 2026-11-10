"""Request checks and the fixed set of static dashboard files."""

import json
import secrets
from http import HTTPStatus
from types import MappingProxyType

from taskrail.core.release import WEB_ASSETS

MAX_BODY = 65536
POST_PATHS = frozenset(("/api/tasks", "/api/actions", "/api/decision"))
SESSION_HEADER = "X-Taskrail-Token"
JAVASCRIPT = "text/javascript; charset=utf-8"
STATIC_ROUTES = MappingProxyType(
    {
        "/": ("dashboard.html", "text/html; charset=utf-8"),
        "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        **{f"/{name}": (name, JAVASCRIPT) for name in WEB_ASSETS if name.endswith(".js")},
    }
)


def error_json(message):
    """A JSON error body."""
    return json.dumps({"error": message})


def post_problem(request):
    """The rejection of a POST as (status, body), or None when it may proceed."""
    headers = request.headers
    token = headers.get(SESSION_HEADER, "")
    authorized = secrets.compare_digest(token, request.server.context["token"])
    if not request.trusted(require_origin=True) or not authorized:
        return HTTPStatus.FORBIDDEN, error_json("Invalid origin or session token. Reload the page.")
    if request.path not in POST_PATHS:
        return HTTPStatus.NOT_FOUND, "{}"
    if headers.get("Content-Type", "").split(";")[0] != "application/json":
        return HTTPStatus.UNSUPPORTED_MEDIA_TYPE, error_json("Expected application/json")
    if not valid_length(headers):
        return HTTPStatus.REQUEST_ENTITY_TOO_LARGE, error_json(
            "Task request must be 1 to 65536 bytes"
        )
    return None


def valid_length(headers):
    """A declared body of 1 to MAX_BODY bytes without chunked transfer."""
    length = headers.get("Content-Length", "0")
    if headers.get("Transfer-Encoding") or not length.isdigit():
        return False
    return 0 < int(length) <= MAX_BODY
