"""Loopback task dashboard with validated, same-origin task submission."""

import secrets
from pathlib import Path

from countersign.observability.progress import say
from countersign.web.http_handler import DashboardServer
from countersign.web.submissions import TaskLauncher

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
TOKEN_BYTES = 32


def make_server(base, port, settings=None, launcher=None):
    """A loopback server with a fresh session token; port 0 picks a free port."""
    root = Path(base).expanduser().resolve()
    context = dict(base=root, launcher=launcher or TaskLauncher(root, settings))
    context["token"] = secrets.token_urlsafe(TOKEN_BYTES)
    return DashboardServer((HOST, port), context)


def serve(base, port=DEFAULT_PORT, settings=None):
    """Serve until interrupted; running task workers are not stopped."""
    with make_server(base, port, settings=settings) as server:
        say(
            f"Countersign: http://{HOST}:{server.server_port} — task dashboard; Ctrl+C stops the server, not active task workers"
        )
        server.serve_forever()
