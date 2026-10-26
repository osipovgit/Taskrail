"""Request checks and the fixed set of static dashboard files."""

import json
import secrets
from http import HTTPStatus
from types import MappingProxyType

MAX_BODY = 65536
POST_PATHS = frozenset(("/api/tasks", "/api/actions", "/api/decision"))
SESSION_HEADER = "X-Countersign-Token"
PAGES = MappingProxyType(
    {
        "/": ("dashboard.html", "text/html; charset=utf-8"),
        "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    }
)
# Browser scripts served from static/; dashboard modules are fixed, never path-derived.
SCRIPTS = frozenset(
    (
        "/dashboard.js",
        "/theme.js",
        *(
            f"/modules/{name}.js"
            for name in (
                "analytics",
                "app",
                "dom",
                "epic",
                "graph",
                "monitor",
                "stages",
                "state",
                "task",
            )
        ),
    )
)
JAVASCRIPT = "text/javascript; charset=utf-8"


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


def static_file(path):
    """(file name, content type) of a fixed dashboard resource, or None."""
    page = PAGES.get(path)
    if page is not None:
        return page
    if path in SCRIPTS:
        return path[1:], JAVASCRIPT
    return None
