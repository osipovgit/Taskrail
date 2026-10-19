"""Loopback HTTP handler: static dashboard files and the JSON API."""

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from countersign.web.analytics import analytics
from countersign.web.http_policy import error_json, post_problem, static_file
from countersign.web.run_activity import BusyError
from countersign.web.run_list import list_runs
from countersign.web.run_view import run_view

STATIC = Path(__file__).parent / "static"
JSON_TYPE = "application/json; charset=utf-8"
READ_SECONDS = 5
SECURITY_POLICY = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
UNAVAILABLE = error_json("Data is unavailable; the stage may still be writing.")
NOT_FOUND = "{}"


class DashboardServer(ThreadingHTTPServer):
    """Carries the run store, launcher and session token to every request."""

    def __init__(self, address, context):
        """Serve the dashboard on a loopback address."""
        super().__init__(address, DashboardHandler)
        self.context = context


class DashboardHandler(BaseHTTPRequestHandler):
    """Only same-host requests are answered; POST also needs the session token."""

    def log_message(self, *args):
        """Requests are not logged."""

    def send(self, status, text, kind=JSON_TYPE):
        """Send a complete, uncached response."""
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", SECURITY_POLICY)
        self.end_headers()
        self.wfile.write(body)

    def trusted(self, require_origin=False):
        """The Host is this loopback server; an Origin, when present or required, matches."""
        host = self.headers.get("Host", "")
        port = self.server.server_port
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return False
        origin = self.headers.get("Origin")
        if origin or require_origin:
            return origin == f"http://{host}"
        return True

    def do_POST(self):
        """Create tasks, run lifecycle actions and record approval decisions."""
        problem = post_problem(self)
        self.send(*(problem or post_result(self)))

    def do_GET(self):
        """Static dashboard files and read-only API views."""
        if not self.trusted():
            return self.send(HTTPStatus.FORBIDDEN, NOT_FOUND)
        try:
            return self.send(*self.get_result(urlsplit(self.path)))
        except (OSError, ValueError, KeyError):
            return self.send(HTTPStatus.NOT_FOUND, UNAVAILABLE)

    def get_result(self, target):
        """(status, body[, type]) of a GET request."""
        resource = static_file(target.path)
        if resource is not None:
            name, kind = resource
            return HTTPStatus.OK, STATIC.joinpath(name).read_text(), kind
        found = api_value(self.server.context, target)
        if found is None:
            return HTTPStatus.NOT_FOUND, NOT_FOUND
        return HTTPStatus.OK, json.dumps(found, ensure_ascii=False)


def post_result(request):
    """Route the JSON payload; a busy workflow is a conflict, invalid input a 400."""
    try:
        outcome = routed(request)
    except (BusyError, BlockingIOError) as error:
        return HTTPStatus.CONFLICT, error_json(str(error))
    except (ValueError, OSError, KeyError) as error:
        return HTTPStatus.BAD_REQUEST, error_json(str(error))
    return HTTPStatus.ACCEPTED, json.dumps(outcome)


def routed(request):
    """Read the bounded body and hand it to the launcher."""
    length = int(request.headers.get("Content-Length", "0"))
    request.connection.settimeout(READ_SECONDS)
    payload = json.loads(request.rfile.read(length).decode("utf-8"))
    return request.server.context["launcher"].route(request.path, payload)


def api_value(context, target):
    """The API view for a path, or None for an unknown path."""
    if target.path == "/api/session":
        return dict(token=context["token"])
    if target.path == "/api/runs":
        return list_runs(context["base"])
    if target.path == "/api/analytics":
        return analytics(context["base"])
    if target.path == "/api/run":
        names = parse_qs(target.query).get("id", [""])
        return run_view(context["base"], names[0])
    return None
