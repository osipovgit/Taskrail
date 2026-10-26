"""Bounded loopback readiness probe for the systemd startup transaction."""

import json
import os
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

STARTUP_SECONDS = 30
POLL_SECONDS = 0.25


def ready(port):
    """Ignore inherited corporate proxies for the local readiness request."""
    request = Request(f"http://127.0.0.1:{port}/api/session")
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=1)
    except OSError:
        return False
    with response:
        payload = json.load(response)
    return isinstance(payload, dict) and isinstance(payload.get("token"), str)


def main():
    """Wait for the application endpoint, not merely an existing process."""
    port = int(os.environ.get("TASKRAIL_WEB_PORT", "8787"))
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        if ready(port):
            return 0
        time.sleep(POLL_SECONDS)
    return 1


if __name__ == "__main__":
    sys.exit(main())
