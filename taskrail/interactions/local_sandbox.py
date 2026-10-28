"""Whether a local request runs in the sandbox, and its sandboxed command line."""

import contextlib

from taskrail.core import protected_paths
from taskrail.infrastructure import sandbox

# A request field: false asks the operator to run the command on the host instead.
FIELD = "sandbox"
# The execution context of a sandboxed command: whether it may write its roots.
WRITES = "sandbox_writes"


def sandboxed(payload):
    """Whether this host can sandbox the command and the request asked for no more."""
    return payload.get(FIELD, True) and sandbox.mode() is not None


def launch(argv, payload, context):
    """Popen arguments of the command: sandboxed when the context says so."""
    writes = context.get(WRITES)
    if writes is None:
        return contextlib.nullcontext(dict(args=argv, pass_fds=()))
    protected = protected_paths.patterns(context.get("config", {}))
    return sandbox.command(argv, payload["cwd"], context["roots"], writes, protected)
