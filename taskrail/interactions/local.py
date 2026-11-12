"""Local diagnostics, sandboxed or personally approved; no implicit shell expansion."""

import subprocess
import tempfile
import time

from taskrail.core import control, json_response, prompt_texts, protected_paths, schema
from taskrail.git import transport
from taskrail.infrastructure import command_status, sandbox, stage_scratch
from taskrail.infrastructure import environment as host_environment
from taskrail.infrastructure.process_group import stop_group
from taskrail.interactions import local_intake, local_request, local_sandbox, read_only

MAX_TIMEOUT = 3600
POLL_SECONDS = 0.1


def extract(text):
    """The request a model meant (see local_intake); the sandbox or an approval gates it."""
    try:
        payload = json_response.extract(text, schema.unique_fields)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("status") != local_intake.STATUS and not local_intake.looks_like(payload):
        return None
    request = local_intake.normalized(payload)
    argv = request["argv"]
    schema.require(
        schema.valid_argv(argv), "Invalid local request: argv must list nonempty argument strings"
    )
    requested = request.get(local_sandbox.FIELD, True)
    schema.require(isinstance(requested, bool), "sandbox must be a boolean")
    schema.contract_version(request["schema_version"])
    return request


def validate(payload, roots, automatic=False, protected=protected_paths.DEFAULT_PATTERNS):
    """A valid request whose executable is installed; returns argv with its absolute path."""
    argv = local_request.checked_request(payload, roots)
    if automatic:
        still = read_only.command(payload, roots, protected)
        schema.require(still, "Automatic read no longer qualifies")
    executable = local_request.executable(argv, payload["cwd"], automatic)
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
    with (
        stage_scratch.command_files(context.get("scratch_directory")),
        local_sandbox.launch(argv, payload, context) as launch,
        tempfile.TemporaryFile() as output,
        tempfile.TemporaryFile() as errors,
    ):
        process = subprocess.Popen(
            **launch[0],
            cwd=payload["cwd"],
            env=context.get("execution_env", host_environment.local_command(context)),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            start_new_session=True,
        )
        context["process_started"] = True
        try:
            monitor(process, (output, errors), context)
        except BaseException:
            reap(process)
            raise
        reap(process)
        return dict(
            command_status.process_outcome(payload["argv"][0], process.returncode, launch[1]),
            stdout=transport.read(output),
            stderr=transport.read(errors),
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


def instructions(stage, host_commands="auto", network=False):
    """Diagnostics run in the sandbox, else on the host at once or after personal approval."""
    advertised = [prompt_texts.text("routes.local")]
    if sandbox.mode():
        route = "routes.local.sandbox.network" if network else "routes.local.sandbox"
        advertised.append(prompt_texts.text(route))
    host = "routes.local.host" if host_commands == "auto" else "routes.local.ask"
    advertised.append(prompt_texts.text(host))
    if stage != "implementer":
        advertised.append(prompt_texts.text("routes.local.read_only"))
    return " ".join(advertised)


def reap(process):
    """Reap the leader and all remaining children."""
    stop_group(process.pid)
    process.wait()
