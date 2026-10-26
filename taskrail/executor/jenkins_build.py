"""Start one root-approved Jenkins build and follow it until it ends or times out.

Nothing is retried: a lost answer after the build was queued is UNKNOWN, because
Jenkins may still run it.
"""

import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode

from taskrail.executor import jenkins_http, jenkins_reads

POLL_SECONDS = 5
QUEUE_ITEM = re.compile(r"/queue/item/([0-9]+)/?$")
UNKNOWN = "UNKNOWN"
FAILED = "FAILED"


def perform(servers, request):
    """The outcome of one build request, as a result entry."""
    server = servers[request["server"]]
    job = jenkins_http.job_url(server, request["job"])
    deadline = time.monotonic() + request["timeout_seconds"]
    try:
        queue = trigger(server, request, job)
    except HTTPError as error:
        error.close()
        return dict(status=FAILED, detail=f"Jenkins refused the build: HTTP {error.code}")
    except (OSError, ValueError):
        return dict(status=UNKNOWN, detail="No answer to the build request; check Jenkins first")
    try:
        return followed(server, queue, job, deadline)
    except (OSError, ValueError):
        return dict(
            status=UNKNOWN,
            queue=queue,
            detail="Lost contact after queueing; inspect this queue item before any new build",
        )


def trigger(server, request, job):
    """POST the build with form parameters; the queue item URL comes from Location."""
    parameterized = server["jobs"][request["job"]]["parameters"]
    url = "{}/{}".format(job, "buildWithParameters" if parameterized else "build")
    form = urlencode(request["parameters"]).encode("utf-8")
    with jenkins_http.call(server, url, form=form) as response:
        match = QUEUE_ITEM.search(response.headers.get("Location", ""))
    if match is None:
        raise ValueError("Jenkins did not return a queue item")
    return "{}/queue/item/{}/api/json".format(server["url"].rstrip("/"), match.group(1))


def followed(server, queue, job, deadline):
    """Wait for the queue to assign a build, then for the build to finish."""
    number = None
    while number is None and time.monotonic() < deadline:
        queued = jenkins_http.get_json(server, queue, jenkins_reads.READ_TIMEOUT)
        if queued.get("cancelled"):
            return dict(status=FAILED, detail="The build was cancelled in the Jenkins queue")
        number = (queued.get("executable") or {}).get("number")
        time.sleep(0 if number else POLL_SECONDS)
    if number is None:
        return dict(
            status=UNKNOWN,
            queue=queue,
            detail="Still queued at the timeout; Jenkins may run it later",
        )
    return finished(server, f"{job}/{number}", deadline)


def finished(server, url, deadline):
    """The build record once it stops running, or its state at the timeout."""
    record = jenkins_reads.status(server, url)["build"]
    while record.get("building") and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        record = jenkins_reads.status(server, url)["build"]
    if record.get("building"):
        detail = "Still running at the timeout; check it with a status request"
        return dict(status=UNKNOWN, build=record, detail=detail)
    status = "SUCCEEDED" if record.get("result") == "SUCCESS" else FAILED
    return dict(status=status, build=record, **jenkins_reads.verification(server, url))
