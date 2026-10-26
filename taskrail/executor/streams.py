"""Run one transport process while keeping only a bounded tail of its output.

The executor service limits file sizes, so output is streamed instead of spooled:
a large remote log cannot kill the transport or exhaust memory.
"""

import functools
import os
import signal
import subprocess
import threading

OUTPUT_LIMIT = 32000
CHUNK = 65536
DRAIN_SECONDS = 5


class OutputTail:
    """The last OUTPUT_LIMIT bytes and the total size of a stream."""

    def __init__(self):
        self.kept = b""
        self.size = 0

    def consume(self, stream):
        """Read until end of stream, discarding all but the tail."""
        for chunk in iter(functools.partial(stream.read1, CHUNK), b""):
            self.size += len(chunk)
            self.kept = (self.kept + chunk)[-OUTPUT_LIMIT:]

    def text(self):
        """The tail as text; invalid UTF-8 is replaced."""
        return self.kept.decode("utf-8", "replace")


def feed(stream, payload):
    """Write the whole payload; a process that exits early simply closes its input."""
    try:
        with stream:
            stream.write(payload)
    except BrokenPipeError:
        return


def run_bounded(argv, payload, environment, timeout):
    """(exit code, output tail); the exit code is None when the timeout killed the process."""
    tail = OutputTail()
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        start_new_session=True,
    ) as process:
        writer = threading.Thread(target=feed, args=(process.stdin, payload), daemon=True)
        writer.start()
        reader = threading.Thread(target=tail.consume, args=(process.stdout,), daemon=True)
        reader.start()
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            exit_code = None
        reader.join(DRAIN_SECONDS)
    return exit_code, tail
