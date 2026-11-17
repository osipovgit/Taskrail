"""Display approved research answers across turns, including incomplete history snapshots."""

import json

from taskrail.application import reviewed_artifacts, run_store
from taskrail.core.files import digest
from taskrail.web import discussions

ANSWER = "answer"
SUMMARY = "summary"
RESEARCH = frozenset(("discussion", "plan"))


def outcome(run, index):
    answer = reviewed_answer(run, index)
    if answer:
        return {ANSWER: answer}
    return {SUMMARY: index.get(SUMMARY, "")}


def reviewed_answer(run, index):
    """Recover an omitted answer only from the exact independently approved no-change plan."""
    if index.get(ANSWER):
        return index[ANSWER]
    finished = index.get("status") in {"NO_CHANGES_REQUIRED", "READY_FOR_REVIEW"}
    if not finished or index.get("plan_review", {}).get("status") != "APPROVE":
        return None
    reference = index.get("results", {}).get("plan")
    if reference and index.get(reviewed_artifacts.SEAL):
        try:
            encoded = reviewed_artifacts.read(run, reference)
        except (OSError, ValueError):
            return None
        if digest(encoded) == index[reviewed_artifacts.SEAL]:
            plan = json.loads(encoded)
            return plan[SUMMARY] if plan.get("decision") == "none" else None
    return None


def earlier_turns(run, fragments):
    """Fill missing answers via server-recorded predecessors; preserve immutable snapshots."""
    if len(fragments) == 1:
        return []
    turns = json.loads(fragments[1])
    if not any(map(missing_answer, turns)):
        return turns
    current = run
    for turn in reversed(turns):
        folder = run.parent / discussions.SUBMISSIONS / current.name
        origin = discussions.link(folder)
        if not origin or origin[1] != turn.get("run"):
            break
        current = run.parent / origin[1]
        if missing_answer(turn):
            restore_answer(current, turn)
    return turns


def missing_answer(turn):
    return turn.get("mode") in RESEARCH and not turn.get(ANSWER)


def restore_answer(run, turn):
    if run.is_symlink():
        return
    try:
        answer = reviewed_answer(run, run_store.read(run))
    except (OSError, ValueError):
        return
    if answer:
        turn.pop(SUMMARY, None)
        turn[ANSWER] = answer
