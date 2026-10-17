"""Bound local subprocess lifetime/output and reap its entire process group."""

import hashlib
import subprocess
import tempfile
import time

from countersign.git import deadline as stage_deadline
from countersign.infrastructure.process_group import stop_group

OUTPUT_LIMIT = 4 * 1024 * 1024
TIMEOUT_SECONDS = 60
POLL_SECONDS = 0.05


def run(argv, root, environment):
    """Never execute a shell; keep potentially large output out of process memory."""
    stage_deadline.check(argv)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            argv,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            start_new_session=True,
        )
        try:
            wait(process, (output, errors))
        except BaseException:
            stop_group(process.pid)
            process.wait()
            raise
        else:
            stop_group(process.pid)
            process.wait()
        return collected(process, output, errors)


def wait(process, streams):
    """Output exhaustion is an uncertain operation, never a successful truncation."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while process.poll() is None:
        stage_deadline.check(process.args)
        if time.monotonic() >= deadline or oversized(streams):
            raise subprocess.TimeoutExpired(process.args, TIMEOUT_SECONDS)
        time.sleep(POLL_SECONDS)
    if oversized(streams):
        raise subprocess.TimeoutExpired(process.args, TIMEOUT_SECONDS)


def read(stream):
    """Decoding preserves a readable transcript; original project bytes are untouched."""
    stream.seek(0)
    return stream.read().decode("utf-8", errors="replace")


def oversized(streams):
    """Treat output limits as explicit failures, never silent truncation."""
    return any(stream.tell() > OUTPUT_LIMIT for stream in streams)


def collected(process, output, errors):
    """Keep an exact byte digest alongside the human-readable command output."""
    completed = subprocess.CompletedProcess(
        process.args, process.returncode, read(output), read(errors)
    )
    output.seek(0)
    completed.stdout_sha256 = hashlib.sha256(output.read()).hexdigest()
    return completed
