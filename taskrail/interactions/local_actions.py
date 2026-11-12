"""Execute an approved local request through its durable replay boundary."""

import json
import subprocess
from pathlib import Path

from taskrail.core.files import digest
from taskrail.infrastructure import environment
from taskrail.interactions import local, local_journal


def previous(run, payload, context=None):
    """Check prior denials and unknown effects before asking for another approval."""
    return local_journal.previous(run, payload, verified_read(payload, context or {}))


def execute(run, folder, payload, context, decision):
    """The caller retains personal approval and source checks around this operation."""
    prepared = dict(context)
    if decision["decision"] == "allow":
        try:
            prepared.update(execution_identity(payload, context))
        except (ValueError, OSError) as error:
            return dict(status="REJECTED", reason=str(error))
    trusted = verified_read(payload, prepared)
    if trusted:
        prepared.update(effective_argv=trusted, verified_read=True)
    earlier = local_journal.previous(run, payload, bool(trusted))
    if earlier is not None:
        return earlier
    entry = local_journal.create(run, folder, payload, prepared, decision)
    if decision["decision"] == "allow":
        outcome = invoke(run, entry, payload, prepared)
    else:
        outcome = dict(status="DECLINED", decision=decision)
    local_journal.update(run, entry, outcome)
    return dict(outcome, action_id=entry["id"])


def execution_identity(payload, context):
    """Freeze executable resolution and environment identity before execution."""
    argv = local.validate(payload, context["roots"], *local.recheck(context))
    execution_env = environment.local_command(context)
    encoded = json.dumps(execution_env, sort_keys=True).encode()
    return dict(
        effective_argv=argv, execution_env=execution_env, environment_sha256=digest(encoded)
    )


def verified_read(payload, context):
    """Only an in-scope read using the system executable can repeat after uncertainty."""
    if "roots" not in context:
        return None
    try:
        return trusted_arguments(payload, context)
    except (OSError, ValueError):
        return None


def trusted_arguments(payload, context):
    """Pin a recognized system read even when PATH uses a different spelling of /usr/bin."""
    roots = context["roots"]
    policy = local.recheck(context)
    safe = local.validate(payload, roots, True, policy[1])
    actual = context.get("effective_argv") or local.validate(payload, roots, *policy)
    system = Path(safe[0]).resolve()
    return safe if Path(actual[0]).resolve() == system else None


def invoke(run, entry, payload, context):
    """Persist RUNNING first; every interruption leaves an explicit UNKNOWN result."""
    local_journal.update(run, entry, dict(status="RUNNING"))
    try:
        return local.execute(payload, context)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        status = "UNKNOWN" if context.get("process_started") else "FAILED"
        return dict(
            status=status, reason=str(error), process_started=bool(context.get("process_started"))
        )
    except BaseException:
        outcome = dict(status="UNKNOWN", reason="Local execution interrupted; inspect effects.")
        local_journal.update(run, entry, outcome)
        raise
