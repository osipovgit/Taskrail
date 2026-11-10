"""Reuse successful observations only for pinned commands over guarded file contents."""

import json
from pathlib import Path

from taskrail.application import evidence, source_tree
from taskrail.core import prompt_texts
from taskrail.core.files import atomic_json, digest
from taskrail.infrastructure import environment
from taskrail.interactions import local_actions, read_grammar

CONTENT_READS = frozenset(("cat", "grep", "head", "tail", "wc"))


def index(folder, payload, context):
    """The same purpose, execution context, source bytes and Git state can use one read."""
    if payload["argv"][0] not in CONTENT_READS:
        return None
    trusted = local_actions.verified_read(payload, context)
    if not trusted:
        return None
    if not monitored_operands(payload, context):
        return None
    identity = [
        payload,
        context["expected"],
        context["git_before"],
        environment.filtered(),
        source_tree.source_stamp(Path(trusted[0])),
        context.get("sandbox_writes"),
    ]
    key = digest(json.dumps(identity, sort_keys=True).encode())
    return folder / "read-receipts" / f"{key}.json"


def monitored_operands(payload, context):
    """Only complete, guarded operands can share content-dependent output."""
    program, *arguments = payload["argv"]
    operands = read_grammar.operands(program, arguments)
    directory = Path(payload["cwd"])
    paths = (directory / operand for operand in operands)
    return bool(operands) and all(guarded(path, context) for path in paths)


def guarded(path, context):
    """Directory listings, ignored files, links and streams are fresh observations."""
    if path.resolve() != path or not path.is_file():
        return False
    for alias, root in context["roots"].items():
        if path.is_relative_to(root):
            name = source_tree.label(alias, root, path)
            return name in context["expected"]
    return False


def previous(index_path):
    """A pointer to the earlier receipt; a removed or changed receipt must be refreshed."""
    if index_path and index_path.exists():
        receipt = json.loads(index_path.read_text())
        path = Path(receipt["path"])
        if receipt["sha256"] == evidence.fingerprint(path):
            return prompt_texts.text("feedback.previous_read", receipt=path)
    return None


def remember(index_path, path):
    """Index a successful file-content observation after its immutable receipt exists."""
    index_path.parent.mkdir(exist_ok=True)
    receipt = dict(path=str(path), sha256=evidence.fingerprint(path))
    atomic_json(index_path, receipt)
