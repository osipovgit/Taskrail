"""Personally approved local diagnostics; no implicit shell expansion."""

import os
import shutil
import subprocess
import tempfile
import time

from taskrail.core import control, json_response, prompt_texts, protected_paths, schema
from taskrail.git import transport
from taskrail.infrastructure import environment as host_environment
from taskrail.infrastructure.process_group import stop_group
from taskrail.interactions import local_request, read_only

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


def validate(payload, roots, automatic=False, protected=protected_paths.DEFAULT_PATTERNS):
    """A valid request whose executable is installed; returns argv with its absolute path."""
    argv = local_request.checked_request(payload, roots)
    if automatic:
        still = read_only.command(payload, roots, protected)
        schema.require(still, "Automatic read no longer qualifies")
    search_path = os.defpath if automatic else None
    executable = shutil.which(argv[0], path=search_path)
    schema.require(bool(executable), "Executable not installed on the orchestrator host")
    return [executable, *argv[1:]]


def recheck(context):
    """Whether an automatic read is rechecked, and against which protected patterns."""
    protected = protected_paths.patterns(context.get("config", {}))
    return context.get("automatic_read", False), protected


def execute(payload, context):
    """Approval authorizes exact argv; execution still has a finite remaining deadline."""
    schema.require(context["timeout"] > 0, "Stage active time exhausted")
    argv = context.get("effective_argv")
    if not argv:
        argv = validate(payload, context["roots"], *recheck(context))
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


def instructions(stage):
    """Diagnostics run as the service user only after explicit personal approval."""
    advertised = [prompt_texts.text("routes.local")]
    if stage != "implementer":
        advertised.append(prompt_texts.text("routes.local.read_only"))
    return " ".join(advertised)


def reap(process):
    """Reap the leader and all remaining children."""
    stop_group(process.pid)
    process.wait()
