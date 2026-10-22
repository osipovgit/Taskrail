"""Personally approved local diagnostics; no implicit shell expansion."""

import os
import shutil
import subprocess
import tempfile
import time

from countersign.core import control, json_response, schema
from countersign.git import transport
from countersign.infrastructure import environment as host_environment
from countersign.infrastructure.process_group import stop_group
from countersign.interactions import local_request, read_only

MAX_TIMEOUT = 3600
POLL_SECONDS = 0.1


def extract(text):
    """Accept one unchanged request object; personal approval still gates execution."""
    try:
        payload = json_response.extract(text, schema.unique_fields)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("status") != "LOCAL_REQUEST":
        return None
    schema.require(
        set(payload) == {"schema_version", "status", "cwd", "argv", "reason"},
        "Invalid local request",
    )
    schema.contract_version(payload["schema_version"])
    return payload


def validate(payload, roots, automatic=False):
    """A valid request whose executable is installed; returns argv with its absolute path."""
    argv = local_request.checked_request(payload, roots)
    if automatic:
        schema.require(read_only.command(payload, roots), "Automatic read no longer qualifies")
    search_path = os.defpath if automatic else None
    executable = shutil.which(argv[0], path=search_path)
    schema.require(bool(executable), "Executable not installed on the orchestrator host")
    return [executable, *argv[1:]]


def execute(payload, context):
    """Approval authorizes exact argv; execution still has a finite remaining deadline."""
    schema.require(context["timeout"] > 0, "Stage active time exhausted")
    argv = context.get("effective_argv") or validate(
        payload, context["roots"], context.get("automatic_read", False)
    )
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            argv,
            cwd=payload["cwd"],
            env=context.get("execution_env", host_environment.filtered()),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            start_new_session=True,
        )
        try:
            monitor(process, (output, errors), context)
        except BaseException:
            reap(process)
            raise
        reap(process)
        return dict(
            exit_code=process.returncode,
            stdout=transport.read(output),
            stderr=transport.read(errors),
            status="SUCCEEDED" if process.returncode == 0 else "FAILED",
        )


def monitor(process, streams, context):
    """Stop cleans the process group; output exhaustion cannot claim success."""
    deadline = time.monotonic() + min(MAX_TIMEOUT, context["timeout"])
    while process.poll() is None:
        control.check_stop(context["run"])
        schema.require(
            time.monotonic() < deadline, "Local command timed out; inspect effects before retry"
        )
        schema.require(not transport.oversized(streams), "Local command output limit exceeded")
        time.sleep(POLL_SECONDS)
    schema.require(not transport.oversized(streams), "Local command output limit exceeded")


def instructions():
    """Diagnostics run as the service user only after explicit personal approval."""
    return (
        "\nLocal commands are available to ALL roles through LOCAL_REQUEST: "
        '{"schema_version":1,"status":"LOCAL_REQUEST","cwd":"/declared/root/or/a/directory/inside",'
        '"argv":["ansible-lint","ansible-playbooks"],"reason":"Purpose, effects and expected result"}. '
        "End the turn; the operator reviews exact argv and may allow, deny or suggest an alternative. "
        "The same session resumes with command output. Do not declare shell unavailable. "
        "Use this for linters, tests and diagnostics; planner/reviewer must not request source fixes. "
        "Commands run without a shell; request bash explicitly if needed. Never request forbidden Git "
        "operations, bypass access denials, or use local commands to run SSH/deployments; use their controlled routes. "
        "User denial is feedback: skip that action, consider the alternative and continue feasible work. "
        "Mandatory unresolved criteria still need honest gaps. Do not resubmit a denied action unchanged.\n"
    )


def reap(process):
    """Reap the leader and all remaining children."""
    stop_group(process.pid)
    process.wait()
