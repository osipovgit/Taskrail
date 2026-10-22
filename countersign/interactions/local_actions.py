"""Execute an approved local request through its durable replay boundary."""

import json
import subprocess

from countersign.core.files import digest
from countersign.infrastructure import environment
from countersign.interactions import local, local_journal


def previous(run, payload, context=None):
    """Check prior denials and unknown effects before asking for another approval."""
    return local_journal.previous(run, payload)


def execute(run, folder, payload, context, decision):
    """The caller retains personal approval and source checks around this operation."""
    earlier = previous(run, payload)
    if earlier is not None:
        return earlier
    prepared = dict(context)
    if decision["decision"] == "allow":
        prepared.update(execution_identity(payload, context))
    entry = local_journal.create(run, folder, payload, prepared, decision)
    if decision["decision"] == "allow":
        outcome = invoke(run, entry, payload, prepared)
    else:
        outcome = dict(status="DECLINED", decision=decision)
    local_journal.update(run, entry, outcome)
    return dict(outcome, action_id=entry["id"])


def execution_identity(payload, context):
    """Freeze executable resolution and environment identity before execution."""
    argv = local.validate(payload, context["roots"], context.get("automatic_read", False))
    execution_env = environment.filtered()
    encoded = json.dumps(execution_env, sort_keys=True).encode()
    return dict(
        effective_argv=argv, execution_env=execution_env, environment_sha256=digest(encoded)
    )


def invoke(run, entry, payload, context):
    """Persist RUNNING first; every interruption leaves an explicit UNKNOWN result."""
    local_journal.update(run, entry, dict(status="RUNNING"))
    try:
        return local.execute(payload, context)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        return dict(status="UNKNOWN", reason=str(error))
    except BaseException:
        outcome = dict(status="UNKNOWN", reason="Local execution interrupted; inspect effects.")
        local_journal.update(run, entry, outcome)
        raise
