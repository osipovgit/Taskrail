"""Durable local action identities; uncertain effects never authorize a replay."""

import json
import uuid

from countersign.core.files import atomic_json, digest

NAME = "local-actions.json"
STATUS = "status"
REQUEST = "request"
SIGNATURE = "request_sha256"
IDENTIFIER = "id"
UNCERTAIN = frozenset(("APPROVED", "RUNNING", "UNKNOWN"))


def signature(payload):
    """Changing a reason cannot make the same command a different action."""
    operation = {key: payload[key] for key in ("cwd", "argv")}
    encoded = json.dumps(operation, sort_keys=True, separators=(",", ":")).encode()
    return digest(encoded)


def records(run):
    """Read the journal independently of model-authored output files."""
    path = run / NAME
    return json.loads(path.read_text()) if path.exists() else []


def previous(run, payload):
    """An unresolved action blocks matching requests even after source changes."""
    identity = signature(payload)
    matching = [entry for entry in records(run) if entry[SIGNATURE] == identity]
    for entry in reversed(matching):
        if entry[STATUS] in UNCERTAIN:
            return dict(
                status="UNKNOWN",
                action_id=entry[IDENTIFIER],
                reason="An earlier local action may have executed; inspect its effects. No replay.",
            )
        if entry[STATUS] == "DECLINED":
            return dict(entry["outcome"], action_id=entry[IDENTIFIER], replayed=False)
    return None


def create(run, folder, payload, context, decision):
    """Persist exact approved inputs before any subprocess can have effects."""
    entry = dict(
        id=uuid.uuid4().hex,
        stage=folder.name,
        request=payload,
        request_sha256=signature(payload),
        source_snapshot=context.get("expected", {}),
        approval=decision,
        effective_argv=context.get("effective_argv", []),
        environment_sha256=context.get("environment_sha256"),
        status="APPROVED" if decision["decision"] == "allow" else "DECLINED",
    )
    atomic_json(run / NAME, [*records(run), entry])
    return entry


def update(run, entry, outcome):
    """Replace one action atomically, retaining its original request and approval."""
    entry.update(status=outcome[STATUS], outcome=outcome)
    identity = entry[IDENTIFIER]
    journal = records(run)
    journal = [entry if prior[IDENTIFIER] == identity else prior for prior in journal]
    atomic_json(run / NAME, journal)
