"""Append continued-session events while parsing only the current turn's verdict."""

from itertools import islice

from countersign.infrastructure import opencode_cli
from countersign.observability.telemetry import Telemetry


def event_lines(path, start):
    """Keep original one-based event line numbers for diagnostic attribution."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return islice(enumerate(lines, 1), start, None)


class TurnIO:
    """Session identity, token limits and allowed secrets are runtime options, not arguments."""

    def __init__(self, attempt, runtime):
        options = runtime or {}
        self.session_id = options.get("session_id")
        self.token_budget = options.get("token_budget")
        self._allow = options.get("env_allow", ())
        self._attachment = options.get("attachment", {})
        self.request = attempt / "request.md"
        self.path = attempt / "events.jsonl"
        self.previous = self.path.read_bytes() if self.session_id else b""
        self._stderr = attempt / "stderr.log"
        self.error_offset = (
            self._stderr.stat().st_size if self.session_id and self._stderr.exists() else 0
        )

    def launch(self, command, model):
        """Never continue the global last session implicitly."""
        argv = list(command) + ["run"]
        if model:
            argv += ["--model", model]
        if self.session_id:
            argv += ["--session", self.session_id]
        environment = dict(opencode_cli.environment(self._allow), **self._attachment)
        environment[opencode_cli.RAW_EVENTS] = str(self.path.with_name("events.raw.jsonl"))
        return argv, environment

    def open(self):
        """Preserve earlier tool calls and usage on a continued turn."""
        return self.path.open("ab" if self.session_id else "wb")

    def telemetry(self):
        """The run-wide token cap includes earlier turns once."""
        telemetry = Telemetry()
        for line in self.previous.splitlines():
            telemetry.observe(line)
        return telemetry

    def prepare(self, prompt):
        """Keep the original request immutable across continuation turns."""
        if prompt != self.request and not self.session_id:
            self.request.write_bytes(prompt.read_bytes())

    def error_stream(self):
        """Keep earlier turn diagnostics while writing the current turn."""
        return self._stderr.open("ab" if self.session_id else "wb")

    def error_text(self):
        """Earlier permission failures cannot poison a later successful turn."""
        with self._stderr.open("rb") as stream:
            stream.seek(self.error_offset)
            return stream.read().decode("utf-8", errors="replace")
