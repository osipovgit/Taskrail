"""Execute typed Git requests under the workflow lock and checkpoint their effects."""

import json

from taskrail.application.artifacts import finish_stage, save_run
from taskrail.core import control
from taskrail.core.files import atomic_json, changed
from taskrail.git import execution, requests, scope

LEDGER = "git-execution.json"


def consume(outcome, active, state, environment):
    """Return updated fingerprints only for a completed, scope-checked Git request."""
    if outcome["status"] != "OK":
        return None
    payload = requests.extract(outcome["final_text"])
    if payload is None:
        return None
    run = active[0].parent
    entries = requests.history(run)
    requests.context(run)
    entry = dict(request=payload, stage=active[0].name, status="RUNNING")
    entries.append(entry)
    atomic_json(run / LEDGER, entries)
    previous = entries[:-1]
    execution.execute(entry, previous, active[1]["role"], environment)
    return complete(entry, entries, active, state, environment)


def complete(entry, entries, active, state, environment):
    """Checkpoint effects before allowing the next model attempt."""
    run = active[0].parent
    after = environment["scan"]()
    metadata = environment["git_metadata"](environment["roots"])
    verify_effects(entry, after, metadata, environment)
    entry["output_file"] = save_output(run, active[0], entry)
    entry["summary"] = "Git {status}: {output_file}".format(**entry)
    atomic_json(run / LEDGER, entries)
    checkpoint(run, after, metadata)
    state["git_jobs"] = entries
    if environment.get("inline"):
        save_run(run, state)
    else:
        finish_stage(run, state, active, dict(status=requests.STATUS, result=entry))
    return after, metadata


def checkpoint(run, after, metadata):
    """A crash before checkpoint publication remains a detectable integrity mismatch."""
    saved = json.loads((run / "checkpoint.json").read_text())
    saved.update(expected=after, git_before=metadata)
    atomic_json(run / "checkpoint.json", saved)


def verify_effects(entry, after, metadata, environment):
    """Unexpected changes keep the RUNNING journal and cannot silently become baseline."""
    if entry.get("mutation") and environment["allowed_paths"]:
        scope.check_paths(environment["allowed_paths"], environment["allowed_paths"])
    control.check_delta(
        changed(environment["expected"], after),
        environment["allowed"] if entry.get("mutation") else [],
        bool(entry.get("mutation")) or metadata == environment["git_before"],
    )


def save_output(run, folder, entry):
    """Persist full stdout/stderr as readable, immutable-by-agent evidence."""
    directory = requests.output_directory(run)
    directory.mkdir(parents=True, exist_ok=True)
    count = len(requests.history(run))
    output = directory / f"{folder.name}-{count}.txt"
    output.write_text(
        "Git request: "
        + json.dumps(entry["request"])
        + "\nStatus: "
        + entry["status"]
        + "\nExit code: "
        + str(entry.get("exit_code", "not executed"))
        + "\nSTDOUT:\n"
        + entry.pop("stdout", "")
        + "\nSTDERR:\n"
        + entry.pop("stderr", ""),
        encoding="utf-8",
    )
    return str(output)
