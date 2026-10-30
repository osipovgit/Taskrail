"""Bind prepared source text only after its receiving model turn completes.

Pending deliveries are not observations. A fresh attempt has another directory and
cannot inherit them; a failed or interrupted dispatch grants no evidence authority.
"""

from taskrail.application import evidence
from taskrail.core.files import atomic_json

PENDING = "pending-evidence.json"


def session_records(context):
    """Current native reads and delivered text of exactly this attempt and model session."""
    folder = context["folder"]
    session = context.get("session_id")
    if not session:
        return []
    observed = evidence.validation_records(context["run"])
    observed = filter(evidence.current, observed)
    return [entry for entry in observed if received(entry, folder, session)]


def received(record, folder, session):
    """Native reads name their event stream; server deliveries name their audience."""
    if record.get("session_id") != session:
        return False
    if record.get("tool") == "read":
        return record.get("source_event") == str(folder / "events.jsonl")
    return record.get("audience") == str(folder)


def queue(folder, text, records):
    """Keep the exact payload and its source records outside the model's permissions."""
    pending = evidence.load_index(folder, PENDING)
    pending[evidence.RECORDS].append(dict(text=text, records=records))
    atomic_json(folder / PENDING, pending)


def confirm(run, folder, prompt, outcome, expected=None):
    """Only text in a completed turn of the expected session becomes delivered."""
    pending = evidence.load_index(folder, PENDING)
    folder.joinpath(PENDING).unlink(missing_ok=True)
    sessions = outcome.get("sessions", [])
    completed = outcome.get("completed") and outcome.get("status") == "OK"
    if not completed or len(sessions) != 1:
        return
    if expected not in (None, sessions[0]):
        return
    records = [
        dict(record, audience=str(folder), session_id=sessions[0])
        for entry in pending[evidence.RECORDS]
        if entry["text"] in prompt
        for record in entry[evidence.RECORDS]
    ]
    index = evidence.load_index(run, evidence.OBSERVATIONS)
    index[evidence.RECORDS].extend(records)
    atomic_json(run / evidence.OBSERVATIONS, index)
