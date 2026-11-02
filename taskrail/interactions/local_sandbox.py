"""Whether a local request runs in the sandbox, and its sandboxed command line."""

import contextlib
import re

from taskrail.core import prompt_texts, protected_paths
from taskrail.infrastructure import sandbox

# Output of a command that needed the network the offline sandbox does not have.
OFFLINE = re.compile(
    r"name resolution|resolve host|getaddrinfo|network is unreachable|"
    r"connection refused|could not connect|max retries exceeded|nodename nor servname",
    re.IGNORECASE,
)
# A request field: false asks the operator to run the command on the host instead.
FIELD = "sandbox"
# The execution context of a sandboxed command: whether it may write its roots.
WRITES = "sandbox_writes"


def sandboxed(payload):
    """Whether this host can sandbox the command and the request asked for no more."""
    return payload.get(FIELD, True) and sandbox.mode() is not None


def offline_note(answer, context):
    """A hint after a sandboxed command that failed for lack of the network, else ""."""
    networked = context.get("config", {}).get("sandbox_network") is True
    if WRITES not in context or networked or answer.get("status") != "FAILED":
        return ""
    streams = (answer.get("stdout", ""), answer.get("stderr", ""))
    if OFFLINE.search("\n".join(streams)) is None:
        return ""
    hint = prompt_texts.text("feedback.offline")
    return f"\n{hint}"


def launch(argv, payload, context):
    """Popen arguments of the command: sandboxed when the context says so."""
    writes = context.get(WRITES)
    if writes is None:
        return contextlib.nullcontext(dict(args=argv, pass_fds=()))
    config = context.get("config", {})
    policy = dict(
        protected=protected_paths.patterns(config), network=config.get("sandbox_network") is True
    )
    return sandbox.command(argv, payload["cwd"], context["roots"], writes, policy)
