"""Carry authenticated, settled Git receipts into an explicitly restarted child."""

from pathlib import Path

from taskrail.application import reviewed_artifacts
from taskrail.core.files import atomic_json
from taskrail.core.schema import require
from taskrail.git import requests
from taskrail.infrastructure.agent_sync import atomic_write

ORIGIN = "origin"


def inherit(workflow, earlier):
    """Preserve successful commits and staged ownership without repeating their writes."""
    entries = {}
    for run in earlier:
        requests.context(run)
        for sequence, entry in enumerate(requests.history(run), 1):
            origin = entry.get(ORIGIN, f"{run.name}-{sequence}")
            if origin not in entries:
                entries[origin] = copied(workflow.run, run, entry, origin)
    if entries:
        workflow.state["git_jobs"] = list(entries.values())
        atomic_json(workflow.run / "git-execution.json", workflow.state["git_jobs"])


def copied(target, source, entry, origin):
    """Retain provenance and give the new session its own immutable output snapshot."""
    require(isinstance(origin, str), "Invalid inherited Git action origin")
    require(Path(origin).name == origin, "Unsafe inherited Git action origin")
    record = dict(entry, origin=origin)
    previous = Path(entry["output_file"]).relative_to(source).as_posix()
    snapshot = reviewed_artifacts.read(source, previous)
    output = requests.output_directory(target) / f"inherited-{origin}.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output, snapshot)
    record["output_file"] = str(output)
    return record
