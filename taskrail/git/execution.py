"""Preflight and execute one durable Git action without model shell access."""

import subprocess

from taskrail.core import prompt_texts
from taskrail.core.files import atomic_json
from taskrail.core.schema import require
from taskrail.git import (
    history_outcome,
    index_ownership,
    policy,
    process,
    requests,
    scope,
    staging_baseline,
)

REQUEST = "request"
STATUS = "status"
ARGV = "argv"
MUTATION = "mutation"
REPOSITORY = "repository"
FINGERPRINT = "fingerprint"
INDEX_WRITES = frozenset(("add", "commit"))
# A write whose outcome is not known is never repeated, even with changed content.
UNCERTAIN = frozenset(("RUNNING", "UNKNOWN"))


def execute(entry, previous, role, environment):
    """Reject before execution, and distinguish an uncertain write from a failed read."""
    try:
        perform(entry, previous, role, environment)
    except ValueError as exc:
        entry.update(status="REJECTED", stderr=str(exc), mutation=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        status = "UNKNOWN" if entry.get(MUTATION) else "FAILED"
        entry.update(status=status, stderr=str(exc))


def perform(entry, previous, role, environment):
    """Record effective argv before the subprocess can produce any side effects."""
    root = requests.root_path(entry[REQUEST], environment["roots"])
    entry[MUTATION] = policy.validate(entry[REQUEST][ARGV], role)
    entry["effective_argv"] = prepare(root, entry, previous, environment)
    overrides = settings(root, entry[REQUEST][ARGV])
    overrides.extend(environment.get("identity_settings", ()))
    atomic_json(environment["run"] / "git-execution.json", [*previous, entry])
    outcome = process.invoke(root, entry["effective_argv"], overrides)
    entry.update(
        status="SUCCEEDED" if outcome.returncode == 0 else "FAILED",
        exit_code=outcome.returncode,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
    )
    index_ownership.record(root, entry)
    staging_baseline.record(entry)


def settings(root, argv):
    """Repository config cannot turn a normal push into mirror or custom execution."""
    overrides = process.filter_settings(root)
    if argv[0] in {"fetch", "push"}:
        remote = argv[1]
        overrides += [
            f"remote.{remote}.mirror=false",
            f"remote.{remote}.receivepack=git-receive-pack",
            f"remote.{remote}.uploadpack=git-upload-pack",
        ]
    return overrides


def prepare(root, entry, previous, environment):
    """Separate immutable policy from source-specific write authorization."""
    payload = entry[REQUEST]
    if not entry[MUTATION]:
        return payload[ARGV]
    same = [record for record in previous if identical(record, payload)]
    require(not any(map(replayed, same)), prompt_texts.text("git.replay"))
    repo = scope.repository(root)
    entry[REPOSITORY] = str(repo)
    history_outcome.prepare(repo, entry)
    entry[FINGERPRINT] = index_ownership.fingerprint(repo, root, payload[ARGV])
    acted_on = [record.get(FINGERPRINT) for record in same]
    require(entry[FINGERPRINT] not in acted_on, prompt_texts.text("git.replay"))
    context = dict(
        repository=repo,
        allowed=environment["allowed_paths"],
        baseline=staging_baseline.updated(staging_baseline.originals(environment), previous, repo),
        owned=index_ownership.owned(previous, repo),
    )
    return scoped_arguments(root, entry, context)


def scoped_arguments(root, entry, context):
    """Keep the authorized effects with the action before it can change Git state."""
    arguments = scope.preflight(root, entry[REQUEST][ARGV], context)
    entry["affected_paths"] = list(map(str, context.get("affected_paths", [])))
    return arguments


def identical(record, payload):
    """The same write to the same root; changing the reason does not make it new."""
    original = record[REQUEST]
    if record[STATUS] == "REJECTED" or original["root"] != payload["root"]:
        return False
    return original[ARGV] == payload[ARGV]


def replayed(record):
    """An identical write is a replay unless it is an add or commit with a known outcome.

    Those act on current content: an add after further edits, or a commit of newly staged
    content, is a new operation once its fingerprint differs.
    """
    command = record[REQUEST][ARGV][0]
    return record[STATUS] in UNCERTAIN or command not in INDEX_WRITES
