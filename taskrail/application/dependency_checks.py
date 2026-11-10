"""Copy historical local execution receipts from approved direct dependencies."""

from pathlib import Path
from tempfile import TemporaryDirectory

from taskrail.application import check_results, feedback_files, reviewed_artifacts
from taskrail.core import delivery_record, schema
from taskrail.core.files import stream_digest
from taskrail.executor import protocol
from taskrail.interactions import local_journal

DIRECTORY = "00-input/dependency-checks"
INDEX = "index.json"
FINISHED = frozenset(("SUCCEEDED", "FAILED"))
SIGNATURE = "dependency_checks_sha256"


def capture(run, parent, step):
    """Publish a child-local packet only when a dependency recorded a completed command."""
    destination = run / DIRECTORY
    with TemporaryDirectory(dir=destination.parent) as temporary:
        folder = Path(temporary) / "packet"
        folder.mkdir()
        receipts = _receipts(folder, parent, step)
        if not receipts:
            return {}
        encoded = feedback_files.context_json(receipts)
        (folder / INDEX).write_text(f"{encoded}\n", encoding="utf-8")
        folder.rename(destination)
    return {SIGNATURE: fingerprint(destination)}


def _receipts(folder, parent, step):
    """The latest accepted run of each dependency already checked by reviewed_sources."""
    receipts = []
    for task in step.get("depends_on", []):
        name = delivery_record.attempts(parent["epic"], task)[-1]
        source = reviewed_artifacts.run_path(parent["run"].parent, name)
        copy_actions(folder, source, task, receipts)
    return receipts


def copy_actions(folder, source, task, receipts):
    """Only commands with an exit code and no observed source mutation are baselines."""
    if not (source / local_journal.NAME).is_file():
        return
    gates = _assessments(source)
    for entry in reviewed_artifacts.document(source, local_journal.NAME):
        finished = entry["status"] in FINISHED and not entry.get("effects")
        if finished and "exit_code" in entry.get("outcome", {}):
            receipt = copy_receipt(folder, len(receipts) + 1, entry)
            receipt.update(task=task, run=source.name)
            receipt.update(gates.get(entry["id"], {}))
            receipts.append(receipt)


def _assessments(source):
    """Associate configured gate assessments by the actual execution identity."""
    if (source / check_results.LEDGER).is_file():
        return {
            row["execution"].get("action_id"): dict(
                check_id=row["check_id"], assessment=row["assessment"]["status"]
            )
            for row in reviewed_artifacts.document(source, check_results.LEDGER)
        }
    return {}


def copy_receipt(folder, sequence, entry):
    """Copy raw streams without letting source paths choose destination filenames."""
    request = entry["request"]
    outcome = entry["outcome"]
    receipt = dict(
        action_id=entry["id"],
        stage=entry["stage"],
        argv=request["argv"],
        cwd=request["cwd"],
        source_sha256=protocol.fingerprint(entry["source_snapshot"]),
        exit_code=outcome["exit_code"],
        status=entry["status"],
    )
    for key in ("stdout", "stderr"):
        name = f"{sequence}.{key}.txt"
        (folder / name).write_text(outcome[key], encoding="utf-8")
        receipt[key] = name
    return receipt


def fingerprint(folder):
    """Bind every filename and its exact contents, rejecting missing or redirected inputs."""
    message = "Dependency check evidence is missing or redirected"
    schema.require(folder.is_dir() and folder == folder.resolve(), message)
    signatures = {}
    for path in folder.iterdir():
        schema.require(path.is_file() and not path.is_symlink(), message)
        signatures[path.name] = stream_digest(path)
    return protocol.fingerprint(signatures)


def index(run, spec):
    """Only advertise historical evidence authenticated by this child's sealed task spec."""
    if SIGNATURE not in spec:
        return None
    folder = run / DIRECTORY
    schema.require(fingerprint(folder) == spec[SIGNATURE], "Dependency check evidence changed")
    return str(folder / INDEX)
