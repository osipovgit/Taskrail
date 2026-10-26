"""Bind typed input fields to their human-readable task file representation."""

import hashlib

LENGTH = "length"


def signature(body):
    """Presentation newlines may differ; typed field strings remain lossless."""
    text = normalized(body)
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    return dict(length=len(text), sha256=fingerprint)


def verify(spec, text):
    """Refuse an edited display body whose typed contract was left unchanged."""
    expected = spec.get("body")
    if expected is None:
        return
    valid = isinstance(expected, dict) and set(expected) == {LENGTH, "sha256"}
    if not valid or not isinstance(expected[LENGTH], int):
        raise ValueError("Invalid task_spec body reference")
    body = normalized(text).partition("\n```\n")[2]
    actual = signature(body[: expected[LENGTH]])
    if expected[LENGTH] < 0 or actual != expected:
        raise ValueError(
            "Task display changed without its typed fields; update task_spec or remove it"
        )


def normalized(text):
    """Match Python's text-file newline handling without modifying stored field values."""
    return text.replace("\r\n", "\n").replace("\r", "\n")
