"""Attribute exits to the requested process using the sandbox's private status channel."""

import json
import tempfile
from contextlib import contextmanager

MAX_EXIT = 255


@contextmanager
def capture(program, base, launch, mounts):
    """Only bubblewrap writes this descriptor. Tool output cannot supply the exit record."""
    with tempfile.TemporaryFile() as status:
        descriptor = status.fileno()
        options = [*launch["args"], "--json-status-fd", str(descriptor)]
        arguments = [program, *base, *options, *mounts]
        descriptors = (*launch["pass_fds"], descriptor)
        yield dict(args=arguments, pass_fds=descriptors), status


def process_outcome(program, returncode, status):
    """Only the named process owns this exit. Sandbox setup failures have no program exit."""
    if status is None and returncode < 0:
        return dict(status="FAILED", signal=-returncode, process_started=True)
    if status is not None:
        return sandbox_outcome(program, returncode, status)
    return exited(program, returncode)


def sandbox_outcome(program, launcher_code, status):
    """An incomplete sandbox setup has no observed command exit."""
    status.seek(0)
    events = [json.loads(line) for line in status]
    codes = [event["exit-code"] for event in events if "exit-code" in event]
    if len(codes) == 1 and valid_exit(codes[0]):
        return exited(program, codes[0])
    uncertain = bool(events) or launcher_code < 0
    return dict(status="UNKNOWN" if uncertain else "FAILED", launcher_exit_code=launcher_code)


def valid_exit(code):
    integer = isinstance(code, int) and not isinstance(code, bool)
    return integer and 0 <= code <= MAX_EXIT


def exited(program, observed):
    return dict(
        status="SUCCEEDED" if observed == 0 else "FAILED",
        exit_code=observed,
        exit_code_of=program,
    )
