"""Preflight and execute one durable Git action without model shell access."""

import json
import subprocess

from taskrail.core.files import atomic_json
from taskrail.core.schema import require
from taskrail.git import index_ownership, policy, process, requests, scope

REQUEST = "request"
STATUS = "status"
ARGV = "argv"
MUTATION = "mutation"
REPOSITORY = "repository"
FINGERPRINT = "fingerprint"
INDEX_WRITES = frozenset(("add", "commit"))
# A write whose outcome is not known is never repeated, even with changed content.
UNCERTAIN = frozenset(("RUNNING", "UNKNOWN"))
REPLAY = "Do not replay a Git write; inspect its saved result"


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
    atomic_json(environment["run"] / "git-execution.json", [*previous, entry])
    outcome = process.invoke(root, entry["effective_argv"], overrides)
    entry.update(
        status="SUCCEEDED" if outcome.returncode == 0 else "FAILED",
        exit_code=outcome.returncode,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
    )
    index_ownership.record(root, entry)


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
    require(not any(map(replayed, same)), REPLAY)
    repo = scope.repository(root)
    entry[REPOSITORY] = str(repo)
    entry[FINGERPRINT] = index_ownership.fingerprint(repo, root, payload[ARGV])
    acted_on = [record.get(FINGERPRINT) for record in same]
    require(entry[FINGERPRINT] not in acted_on, REPLAY)
    context = dict(
        repository=repo,
        allowed=environment["allowed_paths"],
        baseline=baseline(environment),
        owned=index_ownership.owned(previous, repo),
    )
    return scope.preflight(root, payload[ARGV], context)


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


def baseline(environment):
    """Compare staging candidates with the immutable original source manifest."""
    originals = {}
    for name, signature in json.loads(
        (environment["run"] / "00-input/manifest.json").read_text()
    ).items():
        parts = name.split("/", 1)
        path = environment["roots"][parts[0]] / parts[1]
        originals[str(path)] = signature
    return originals
