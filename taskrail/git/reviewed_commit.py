"""Finalize reviewed source through the same durable executor as model Git requests."""

from pathlib import Path

from taskrail.core.files import atomic_json
from taskrail.core.schema import require
from taskrail.git import dispatch, execution, process, requests, reviewed_index

STAGE = "task-commit"
REVIEWED = "reviewed_paths"
LEDGER = "git-execution.json"
UNKNOWN = frozenset(("RUNNING", "UNKNOWN"))
IDENTITY = ("user.name=Taskrail", "user.email=taskrail@localhost")


def commit(environment, root, paths, message):
    """Stage exact reviewed paths, then require a verified controlled commit receipt."""
    run = environment["run"]
    requests.context(run)
    previous = reviewed_index.completed(run, root, paths, REVIEWED in environment)
    if previous:
        return previous
    if REVIEWED in environment:
        to_stage = reviewed_index.pending(root, paths)
    else:
        to_stage = [] if reviewed_index.staged(run, root, paths) else paths
    if to_stage:
        invoke(environment, root, ["add", "--", *to_stage])
    staged = reviewed_index.staged_paths(root)
    if REVIEWED in environment and not set(staged).intersection(environment[REVIEWED]):
        require(
            reviewed_index.committed_files(root, paths, "HEAD"), "Reviewed Git changes are unstaged"
        )
        return None
    if not staged:
        return None
    entry = invoke(commit_environment(environment, root), root, ["commit", "-m", message])
    return entry["source_baseline"]["head"]


def commit_environment(environment, root):
    """The fallback author is server-owned; request arguments cannot choose Git settings."""
    author = process.invoke(root, ["config", "user.email"]).stdout.strip()
    author_settings = () if author else IDENTITY
    return dict(environment, identity_settings=(*author_settings, "commit.cleanup=verbatim"))


def invoke(environment, root, argv):
    """Journal before mutation; source drift or interruption never becomes a receipt."""
    run = environment["run"]
    previous = requests.history(run)
    entry = dict(request=payload(root, argv), stage=STAGE, status="RUNNING")
    atomic_json(run / LEDGER, [*previous, entry])
    try:
        execute_checked(environment, entry, previous)
    except BaseException:
        entry.update(status="UNKNOWN", stderr="Commit interrupted; inspect source and Git effects")
        atomic_json(run / LEDGER, [*previous, entry])
        raise
    publish(run, previous, entry)
    require(entry["status"] == "SUCCEEDED", entry.get("summary", "Controlled commit failed"))
    return entry


def execute_checked(environment, entry, previous):
    """Git may change its own metadata, never the source accepted by the reviewer."""
    require(environment["scan"]() == environment["expected"], "Reviewed source changed")
    execution.execute(entry, previous, "implementer", environment)
    if REVIEWED in environment and entry.get("source_baseline"):
        root = Path(entry["repository"])
        names = [path.relative_to(root).as_posix() for path in environment[REVIEWED]]
        head = entry["source_baseline"]["head"]
        require(reviewed_index.committed_files(root, names, head), "Incomplete reviewed commit")
    require(environment["scan"]() == environment["expected"], "Reviewed source changed")


def payload(root, argv):
    """Server-generated arguments still pass the controlled Git grammar and ownership checks."""
    return dict(
        schema_version=1,
        status=requests.STATUS,
        root=str(root),
        argv=argv,
        reason="reviewed-task-finalization",
    )


def publish(run, previous, entry):
    """Keep ordinary Git output artifacts and durable receipts for recovery and the report."""
    error = entry.get("stderr") or entry["status"]
    entry["output_file"] = dispatch.save_output(run, run / STAGE, entry)
    entry["summary"] = error
    atomic_json(run / LEDGER, [*previous, entry])


def require_settled(run):
    """A new child cannot bypass an uncertain finalization in an earlier attempt."""
    pending = any(
        entry.get("stage") == STAGE and entry["status"] in UNKNOWN
        for entry in requests.history(run)
    )
    require(not pending, "Earlier task commit is uncertain; inspect Git before restarting")
