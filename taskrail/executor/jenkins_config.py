"""Root-managed Jenkins servers, credentials and the jobs agents may use."""

import json
import re
from pathlib import Path

from taskrail.core.schema import require
from taskrail.executor import hosts, protocol

CONFIG = Path("/etc/taskrail-executor/jenkins.json")
URL = "url"
USERNAME = "username"
JOBS = "jobs"
PATH = "path"
APPROVAL = "approval"
# root: every build waits for root approval (the default); none: root allowed this
# job's builds in advance by configuring it, for jobs that change nothing outside CI.
APPROVALS = frozenset(("root", "none"))
CA_FILE = "ca_file"
SERVER_FIELDS = frozenset((URL, USERNAME, "token", JOBS))
URL_PATTERN = re.compile(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?")
JOB_PATH = re.compile(r"(?!\.{1,2}(/|$))[A-Za-z0-9 ._-]+(/(?!\.{1,2}(/|$))[A-Za-z0-9 ._-]+)*")
PARAMETER = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")


def load(path=CONFIG):
    """Validated servers; a missing file means Jenkins is not configured."""
    if not path.exists():
        return {}
    servers = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(servers, dict), "Jenkins configuration must be an object")
    for alias, server in servers.items():
        protocol.label(alias)
        check_server(server)
    return servers


def check_server(server):
    """Exact fields, an http(s) base URL without credentials, and an allowlist of jobs."""
    require(isinstance(server, dict), "Each Jenkins server must be an object")
    extra = set(server) - SERVER_FIELDS - {CA_FILE}
    require(set(server) >= SERVER_FIELDS and not extra, "Server fields: url, username, token, jobs")
    require(matches(URL_PATTERN, server[URL]), "Jenkins url must be http(s)://host[:port][/path]")
    protocol.text(server[USERNAME])
    protocol.text(server["token"])
    ca_file = server.get(CA_FILE)
    if ca_file is not None:
        hosts.validate_identity(ca_file)
    check_jobs(server[JOBS])


def check_jobs(jobs):
    """Job aliases map to folder paths, the build parameters agents may set and approval."""
    require(isinstance(jobs, dict) and bool(jobs), "Configure at least one Jenkins job")
    for alias, job in jobs.items():
        protocol.label(alias)
        fields = set(job) if isinstance(job, dict) else set()
        require(fields - {APPROVAL} == {PATH, "parameters"}, "Each job needs path and parameters")
        require(job.get(APPROVAL, "root") in APPROVALS, 'Job approval is "root" or "none"')
        require(matches(JOB_PATH, job[PATH]), "Job path: folder/name segments")
        names = job["parameters"]
        require(isinstance(names, list), "Job parameters must be a list of names")
        require(all(matches(PARAMETER, name) for name in names), "Invalid parameter name")


def matches(pattern, text):
    """A string that fully matches the pattern."""
    return isinstance(text, str) and pattern.fullmatch(text) is not None


def public(servers):
    """Server URLs, accounts and jobs, never tokens."""
    return {alias: shown(server) for alias, server in servers.items()}


def shown(server):
    """The non-secret fields of one server."""
    return {key: server[key] for key in (URL, USERNAME, JOBS)}


def identity(servers, request):
    """What a build approval covers: the server account and the exact job path."""
    server = servers[request["server"]]
    job = server[JOBS][request["job"]]
    return {URL: server[URL], USERNAME: server[USERNAME], "job_path": job[PATH]}
