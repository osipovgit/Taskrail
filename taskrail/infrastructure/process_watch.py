"""Watch one opencode process: Stop, deadline, token budget and permission denials."""

import contextlib
import subprocess
import time

from taskrail.core.control import check_stop
from taskrail.core.files import atomic_json
from taskrail.infrastructure import opencode_cli, usage_limits
from taskrail.infrastructure.event_summary import decoded
from taskrail.infrastructure.process_group import stop_group
from taskrail.observability.activity import Progress
from taskrail.observability.progress import say

SUCCESS = "OK"
POLL_SECONDS = 0.2
PROGRESS_SECONDS = 30
EVENTS = "events.jsonl"
OFFSET = "offset"
PENDING = "pending"
ERROR = "error"


class TurnWatch:
    """Stream new events into activity and telemetry while the process runs."""

    def __init__(self, turn, attempt, progress):
        """Continue after the events of earlier turns of the same session."""
        started = time.monotonic()
        self.turn = turn
        self.attempt = attempt
        self.activity = Progress(attempt / "activity.json")
        self.telemetry = turn.telemetry()
        self.stream = {OFFSET: len(turn.previous), PENDING: b""}
        self.clock = dict(started=started, progress=progress, next=started + PROGRESS_SECONDS)

    def launch(self, argv, env, workspace, timeout):
        """Return (status, exit code); the process group is always stopped."""
        with self.turn.open() as output, self.turn.error_stream() as errors:
            status = turn_status(self.telemetry, self.turn.budgets, [])
            if status != SUCCESS:
                return status, None
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    env=env,
                    start_new_session=True,
                )
            except OSError as error:
                errors.write(str(error).encode())
                return "LAUNCH_ERROR", None
            return self.supervise(process, timeout)

    def supervise(self, process, timeout):
        """A timeout stops the group; any other interruption propagates after cleanup."""
        try:
            return self.follow(process, time.monotonic() + timeout)
        except subprocess.TimeoutExpired:
            stop_group(process.pid)
            return "TIMEOUT", process.wait()
        except BaseException:
            stop_group(process.pid)
            process.wait()
            raise
        finally:
            stop_group(process.pid)

    def follow(self, process, deadline):
        """Poll events until exit, a budget stop, a denial or the deadline."""
        while True:
            check_stop(self.attempt.parent)
            status = turn_status(self.telemetry, self.turn.budgets, self.read())
            if status != SUCCESS:
                stop_group(process.pid)
                return status, process.wait()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, remaining)
            with contextlib.suppress(subprocess.TimeoutExpired):
                return SUCCESS, process.wait(timeout=min(POLL_SECONDS, remaining))
            announce(self)

    def read(self):
        """Complete new lines; a partial last line waits for the next poll."""
        with self.attempt.joinpath(EVENTS).open("rb") as stream:
            stream.seek(self.stream[OFFSET])
            chunk = stream.read()
            self.stream[OFFSET] = stream.tell()
        lines = (self.stream[PENDING] + chunk).split(b"\n")
        self.stream[PENDING] = lines.pop()
        if lines:
            self.observe(lines)
        return lines

    def observe(self, lines):
        """Update public activity and usage telemetry."""
        self.activity.observe(lines)
        for line in lines:
            self.telemetry.observe(line)
        atomic_json(self.attempt / "telemetry.json", self.telemetry.summary())

    def drain(self):
        """Read everything left after the process stopped, including a partial line."""
        with self.attempt.joinpath(EVENTS).open("rb") as stream:
            stream.seek(self.stream[OFFSET])
            rest = stream.read()
        self.observe((self.stream[PENDING] + rest).splitlines())


def announce(watch):
    """A progress line every 30 seconds when progress is enabled."""
    now = time.monotonic()
    if not watch.clock["progress"] or now < watch.clock["next"]:
        return
    size = watch.attempt.joinpath(EVENTS).stat().st_size
    say(watch.activity.line(now - watch.clock["started"], size))
    watch.clock["next"] = now + PROGRESS_SECONDS


def turn_status(telemetry, budgets, lines):
    """Stop on an exceeded token budget or a denied tool call."""
    status = usage_limits.exceeded(telemetry, **budgets)
    if status == SUCCESS and any(permission_denied_event(line) for line in lines):
        return "BLOCKED_PERMISSION"
    return status


def permission_denied_event(line):
    """A denied tool call or a denial error in one raw event line."""
    event = decoded(line)
    if event is None:
        return False
    return opencode_cli.permission_error(event_error(event))


def event_error(event):
    """The error text of a failed tool call or an error event."""
    if event.get("type") == ERROR:
        return str(event.get(ERROR, ""))
    state = event.get("part", {}).get("state", {})
    if event.get("type") != "tool_use" or not isinstance(state, dict):
        return ""
    if state.get("status") != ERROR:
        return ""
    return str(state.get(ERROR, ""))
