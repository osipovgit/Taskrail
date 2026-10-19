"""Read-only Jenkins operations: build status, console tail and test summary."""

from urllib.error import HTTPError

from countersign.executor import jenkins_http, streams

READ_TIMEOUT = 20
STATUS_TREE = "number,result,building,duration,timestamp,url,displayName,description"
TEST_TREE = "passCount,failCount,skipCount,suites[cases[className,name,status,errorDetails]]"
FAILED_CASES = frozenset(("FAILED", "REGRESSION"))
MAX_CASES = 100


def build_url(server, request):
    """The job URL plus lastBuild or an explicit build number."""
    build = request["build"]
    reference = "lastBuild" if build == "last" else str(build)
    return "{0}/{1}".format(jenkins_http.job_url(server, request["job"]), reference)


def read(servers, request):
    """Run one read operation; a missing build or report is a result, not an error."""
    server = servers[request["server"]]
    operation = dict(status=status, console=console, tests=tests)[request["operation"]]
    try:
        outcome = operation(server, build_url(server, request))
    except HTTPError as error:
        error.close()
        return dict(status="FAILED", http_status=error.code, detail=str(error.reason))
    return dict(outcome, status="SUCCEEDED")


def status(server, url):
    """Build number, result, whether it still runs, and timing."""
    query = f"{url}/api/json?tree={STATUS_TREE}"
    return dict(build=jenkins_http.get_json(server, query, READ_TIMEOUT))


def console(server, url):
    """The last part of the console log; the log is streamed, only its tail is kept."""
    tail = streams.OutputTail()
    with jenkins_http.call(server, f"{url}/consoleText", timeout=READ_TIMEOUT) as response:
        tail.consume(response)
    truncated = tail.size > streams.OUTPUT_LIMIT
    return dict(console=tail.text(), size=tail.size, truncated=truncated)


def tests(server, url):
    """Pass, fail and skip counts with up to 100 failed cases."""
    query = f"{url}/testReport/api/json?tree={TEST_TREE}"
    report = jenkins_http.get_json(server, query, READ_TIMEOUT)
    counts = {key: report.get(key) for key in ("passCount", "failCount", "skipCount")}
    return dict(tests=dict(counts, failed_cases=failed_cases(report)[:MAX_CASES]))


def failed_cases(report):
    """Failed or regressed cases of every suite."""
    suites = report.get("suites", [])
    cases = [case for suite in suites for case in suite.get("cases", [])]
    return [case for case in cases if case.get("status") in FAILED_CASES]
