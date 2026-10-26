"""Authenticated Jenkins HTTP calls that never follow redirects or use proxies.

A redirect could carry the API token to another host, so 3xx answers are errors.
"""

import base64
import json
import ssl
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

JSON_LIMIT = 4 * 1024 * 1024
DEFAULT_TIMEOUT = 30


class NoRedirect(HTTPRedirectHandler):
    """Turn every redirect into an HTTPError."""

    def redirect_request(self, request, response, code, *details):
        """Refuse to follow; the caller sees the 3xx status."""
        raise HTTPError(request.full_url, code, "Refused a redirect", details[1], response)


def job_url(server, job):
    """The job's base URL; folders become nested /job/ segments."""
    path = server["jobs"][job]["path"]
    parts = [quote(part, safe="") for part in path.split("/")]
    return "{}/job/{}".format(server["url"].rstrip("/"), "/job/".join(parts))


def call(server, url, form=None, timeout=DEFAULT_TIMEOUT):
    """One request with Basic authentication; a form body turns it into a POST."""
    context = ssl.create_default_context(cafile=server.get("ca_file"))
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect)
    method = "GET" if form is None else "POST"
    request = Request(url, data=form, method=method)
    request.add_header("Authorization", f"Basic {credentials(server)}")
    return opener.open(request, timeout=timeout)


def credentials(server):
    """The Basic authentication value of the configured account."""
    account = "{}:{}".format(server["username"], server["token"])
    return base64.b64encode(account.encode("utf-8")).decode("ascii")


def get_json(server, url, timeout):
    """A bounded JSON document."""
    with call(server, url, timeout=timeout) as response:
        document = response.read(JSON_LIMIT + 1)
    if len(document) > JSON_LIMIT:
        raise ValueError("Jenkins response exceeds 4 MiB")
    return json.loads(document)
