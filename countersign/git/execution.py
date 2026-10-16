"""Preflight and execute one durable Git action without model shell access."""

import json
import subprocess

from countersign.core.files import atomic_json
from countersign.core.schema import require
from countersign.git import policy, process, requests, scope

REQUEST = "request"
STATUS = "status"
ARGV = "argv"
MUTATION = "mutation"


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
    require(
        not any(replayed(record, payload) for record in previous),
        "Do not replay a Git write; inspect its saved result",
    )
    context = dict(
        allowed=environment["allowed_paths"],
        baseline=baseline(environment),
        managed_index=managed_index(previous),
    )
    return scope.preflight(root, payload[ARGV], context)


def replayed(record, payload):
    """Changing the reason does not authorize replay of an identical write."""
    original = record[REQUEST]
    same_root = original["root"] == payload["root"]
    same = same_root and original[ARGV] == payload[ARGV]
    return same and record[STATUS] != "REJECTED"


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


def managed_index(previous):
    """Only an index whose last controlled mutation was add may be committed."""
    stages = [record for record in previous if record.get(MUTATION)]
    if not stages:
        return False
    latest = stages[-1]
    command = latest[REQUEST][ARGV][0]
    return latest[STATUS] == "SUCCEEDED" and command == "add"
