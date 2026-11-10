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
    worktree_restore,
)

REQUEST = "request"
STATUS = "status"
ARGV = "argv"
MUTATION = "mutation"
REPOSITORY = "repository"
FINGERPRINT = "fingerprint"
CONTENT_WRITES = frozenset(("add", "commit", "restore"))
# A write whose outcome is not known is never repeated, even with changed content.
UNCERTAIN = frozenset(("RUNNING", "UNKNOWN"))


def execute(entry, previous, role, environment):
    """Reject before execution, and distinguish an uncertain write from a failed read."""
    try:
        perform(entry, previous, role, environment)
    except ValueError as exc:
        entry.update(status="REJECTED", stderr=str(exc), mutation=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        uncertain = entry.get(MUTATION) and "effective_argv" in entry
        entry.update(
            status="UNKNOWN" if uncertain else "FAILED", stderr=str(exc), mutation=bool(uncertain)
        )


def perform(entry, previous, role, environment):
    """Record effective argv before the subprocess can produce any side effects."""
    root = requests.root_path(entry[REQUEST], environment["roots"])
    arguments = entry[REQUEST][ARGV]
    entry[MUTATION] = policy.validate(arguments, role, environment.get("config"))
    arguments = prepare(root, entry, previous, environment)
    overrides = settings(root, entry[REQUEST][ARGV])
    overrides.extend(environment.get("identity_settings", ()))
    running = dict(entry, effective_argv=arguments)
    atomic_json(environment["run"] / "git-execution.json", [*previous, running])
    entry["effective_argv"] = arguments
    outcome = process.invoke(root, entry["effective_argv"], overrides)
    entry.update(
        status="SUCCEEDED" if outcome.returncode == 0 else "FAILED",
        exit_code=outcome.returncode,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
    )
    index_ownership.record(root, entry)
    worktree_restore.record(entry)
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
    arguments = payload[ARGV]
    if not entry[MUTATION]:
        return arguments
    same = [record for record in previous if record[STATUS] in UNCERTAIN]
    require(
        not any(record.get(MUTATION) for record in same),
        prompt_texts.text("git.unknown"),
    )
    same = [record for record in previous if identical(record, payload)]
    require(not any(map(replayed, same)), prompt_texts.text("git.replay"))
    repo = scope.repository(root)
    entry[REPOSITORY] = str(repo)
    history_outcome.prepare(repo, entry)
    if arguments[0] == "restore":
        entry[FINGERPRINT] = worktree_restore.fingerprint(repo, root, arguments)
    else:
        entry[FINGERPRINT] = index_ownership.fingerprint(
            repo, root, arguments, environment.get("reviewed_paths")
        )
    scope.preserve_for_review(
        entry[FINGERPRINT], arguments[0], environment.get("review_only_paths")
    )
    require(
        all(record.get(FINGERPRINT) != entry[FINGERPRINT] for record in same),
        prompt_texts.text("git.replay"),
    )
    context = dict(
        repository=repo,
        allowed=set(environment["allowed_paths"]) - set(environment.get("review_only_paths", [])),
        reviewed=environment.get("reviewed_paths"),
        adopted=set(environment.get("adopted_paths", [])),
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
    if not record.get(MUTATION) or original["root"] != payload["root"]:
        return False
    return original[ARGV] == payload[ARGV]


def replayed(record):
    """An identical write is a replay unless it is an add or commit with a known outcome.

    Those act on current content: an add after further edits, or a commit of newly staged
    content, is a new operation once its fingerprint differs.
    """
    command = record[REQUEST][ARGV][0]
    return record[STATUS] in UNCERTAIN or command not in CONTENT_WRITES
