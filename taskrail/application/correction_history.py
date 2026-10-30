"""Completed corrective writers remain mandatory lineage of every later acceptance."""

from taskrail.application import check_configuration, reviewed_artifacts, step_checks
from taskrail.core import corrections, delivery_record
from taskrail.core.files import digest
from taskrail.core.schema import require
from taskrail.git import requests, reviewed_commit

STATUS = "status"
RUN = "run"


def completed(parent, exclude=None):
    """No new review or correction can hide an unresolved earlier corrective writer."""
    entries = corrections.records(delivery_record.read(parent))
    completed_runs = []
    for entry in entries:
        if entry[RUN] != exclude:
            run = reviewed_artifacts.run_path(parent.parent, entry[RUN])
            state = reviewed_artifacts.document(run, "run.json")
            validate(run, parent, state)
            completed_runs.append((run, state))
    return completed_runs


def validate(run, parent, state):
    """Only a completed linked phase with settled Git and verified commit receipts qualifies."""
    require(state.get("phase") == corrections.PHASE, "Invalid correction phase")
    require(state.get("check_parent") == parent.name, "Correction parent changed")
    require(
        state[STATUS] in {"READY_FOR_REVIEW", "NO_CHANGES_REQUIRED"},
        "Unresolved correction needs operator attention before integration review",
    )
    journal = requests.history(run)
    require(
        not any(entry[STATUS] in reviewed_commit.UNKNOWN for entry in journal),
        "Correction Git outcome is uncertain; inspect its journal",
    )
    committed(state, journal)


def committed(state, journal):
    """An isolated correction must retain the successful receipt for every changed root."""
    if not state.get("task_branch"):
        return
    changed = state.get("changed_files", [])
    aliases = {name.split("/", 1)[0] for name in changed}
    commits = {entry["root"]: entry for entry in state.get("commits", [])}
    for alias in aliases:
        verified_commit(commits.get(alias, {}), journal, state["roots"][alias])


def verified_commit(entry, journal, repository):
    """Every changed root must name a completed controlled commit."""
    revision = entry.get("commit")
    require(revision and "error" not in entry, "Correction has no verified commit")
    require(receipt(journal, repository, revision), "Correction commit receipt is missing")


def receipt(journal, repository, revision):
    """The durable controlled executor, not a model summary, attests to each commit."""
    commits = []
    for entry in journal:
        if entry.get("stage") != reviewed_commit.STAGE:
            continue
        request = entry.get("request", {})
        if request.get("argv", [])[:1] == ["commit"]:
            commits.append(entry)
    return any(
        record[STATUS] == "SUCCEEDED"
        and record.get("repository") == repository
        and (record.get("source_baseline") or {}).get("head") == revision
        for record in commits
    )


def required(parent, selected, config, exclude=None):
    """Reviewed corrective gates accumulate without changing the original parent plan."""
    names = list(selected)
    for run, state in completed(parent, exclude):
        settings = check_configuration.parent_settings(run, state)
        require(
            check_configuration.fingerprint(settings) == check_configuration.fingerprint(config),
            "Correction check catalog changed",
        )
        names.extend(step_checks.names(reviewed_plan(run, state)))
    selected = list(dict.fromkeys(names))
    step_checks.validate(selected, config.get("check_recipes", {}))
    return selected


def reviewed_plan(run, state):
    """Only the sealed independent plan approval may add new mandatory local gates."""
    reference = state.get("results", {}).get("plan")
    require(bool(reference), "Correction plan is missing")
    encoded = reviewed_artifacts.read(run, reference)
    require(
        digest(encoded) == state.get(reviewed_artifacts.SEAL), "Correction reviewed plan changed"
    )
    plan = reviewed_artifacts.document(run, reference)
    names = step_checks.names(plan)
    inherited = set(state.get(step_checks.KEY, []))
    require(set(names) <= inherited, "Correction required gates changed")
    return plan
