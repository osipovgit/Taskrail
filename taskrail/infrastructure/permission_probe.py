"""Recover a read-only CLI permission listing before interpreting its policy."""

import subprocess
import time

from taskrail.core import control, corrections
from taskrail.infrastructure import opencode_cli, opencode_server
from taskrail.infrastructure.process_group import stop_group
from taskrail.observability.progress import say

# A 2.x probe starts a private server and then waits for its agent catalog.
LISTING_SECONDS = 2 * opencode_server.READY_SECONDS
POLL_SECONDS = 0.1


class Unavailable(ValueError):
    """The permission probe exited unsuccessfully or timed out."""


def verify(launch, cwd, log):
    """Use the existing transport allowance, retaining diagnostics before each retry."""
    retries = corrections.setting(launch, "transport_retries", 3)
    for attempt in range(retries + 1):
        try:
            invoke(launch, cwd, log)
        except Unavailable as error:
            failure(log, error, attempt + 1, retries - attempt)
        else:
            return


def failure(log, error, number, remaining):
    """A terminal failure keeps its log too; Stop is checked by the next invocation."""
    archive = log.with_name(f"{log.stem}-failed-{number}{log.suffix}")
    archive.write_bytes(log.read_bytes())
    if not remaining:
        raise error
    say(f"Permission preflight retry after attempt {number}: {error}; saved {archive}")


def invoke(launch, cwd, log):
    """Only a successful process exit lets the caller inspect the effective policy."""
    code = run_listing(
        launch["command"], cwd, log, launch["agent_env_allow"], launch.get("stop_run")
    )
    if code:
        raise Unavailable(
            f"opencode permission probe exited with code {code}; no model launched; inspect {log}"
        )


def run_listing(command, cwd, log, allow=(), stop_run=None):
    """Run the configured CLI and always reap the probe's process group."""
    if stop_run is not None:
        control.check_stop(stop_run)
    with log.open("wb") as output:
        process = subprocess.Popen(
            [*command, "agent", "list"],
            cwd=cwd,
            env=opencode_cli.environment(allow),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return wait_listing(process, stop_run)
        except subprocess.TimeoutExpired:
            stop_group(process.pid)
            process.wait()
            raise Unavailable(
                f"opencode did not list agent permissions within {LISTING_SECONDS} seconds;"
                f" no model launched; inspect {log}"
            ) from None
        except BaseException:
            stop_group(process.pid)
            process.wait()
            raise
        finally:
            stop_group(process.pid)


def wait_listing(process, run):
    """Bound a probe while honoring Stop, including before its first model turn."""
    deadline = time.monotonic() + LISTING_SECONDS
    while time.monotonic() < deadline:
        if run is not None:
            control.check_stop(run)
        code = process.poll()
        if code is not None:
            return code
        remaining = max(0, deadline - time.monotonic())
        time.sleep(min(POLL_SECONDS, remaining))
    raise subprocess.TimeoutExpired(process.args, LISTING_SECONDS)
