"""Capture complete SSH output and bounded Jenkins console previews."""

import functools
import os
import signal
import subprocess
import tempfile

OUTPUT_LIMIT = 32000
CHUNK = 65536


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


def execute(argv, payload, environment, timeout):
    """Spool output while SSH runs and retain the full result, including on timeout."""
    with tempfile.TemporaryFile() as output:
        with subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=output,
            env=environment,
            start_new_session=True,
        ) as process:
            try:
                process.communicate(payload, timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                code = None
            else:
                code = process.returncode
        output.seek(0)
        return code, output.read().decode("utf-8", "replace")
