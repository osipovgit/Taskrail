"""Bounded, interruptible reading of the private server's readiness announcement."""

import json
import os
import selectors
import time
from urllib.parse import urlsplit

POLL_SECONDS = 0.1
MAX_BYTES = 8192
INVALID = "Invalid opencode server readiness URL"
HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))


def wait(process, startup):
    """Read one complete announcement without blocking on silence or a partial line."""
    deadline = time.monotonic() + startup["timeout"]
    received = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            checkpoint(startup)
            remaining = max(0, min(POLL_SECONDS, deadline - time.monotonic()))
            if selector.select(remaining):
                url = announcement(process, received)
                if url is not None:
                    return url
    raise TimeoutError("opencode server readiness timed out")


def checkpoint(startup):
    """The workflow's Stop file also applies before its first turn."""
    if startup.get("check") is not None:
        startup["check"]()


def announcement(process, received):
    """Read only currently available bytes; EOF and oversized messages fail closed."""
    chunk = os.read(process.stdout.fileno(), MAX_BYTES)
    if not chunk:
        raise ValueError("opencode server exited before readiness")
    received.extend(chunk)
    if len(received) > MAX_BYTES:
        raise ValueError("opencode server readiness announcement is too large")
    if b"\n" in received:
        return address(received.split(b"\n", 1)[0])
    return None


def address(announcement):
    """Accept only a structured announcement with a string endpoint."""
    ready = json.loads(announcement)
    url = ready.get("url") if isinstance(ready, dict) else None
    if not isinstance(url, str):
        raise ValueError(INVALID)
    return local_url(url)


def local_url(url):
    """A private server can only advertise a local HTTP port without credentials."""
    parsed = urlsplit(url)
    local = parsed.scheme == "http" and parsed.hostname in HOSTS
    if not local or not parsed.port or parsed.username or parsed.password:
        raise ValueError(INVALID)
    return url
