"""Model text of a stage as chat messages."""

import json

from taskrail.web.run_files import TEXT, TRUNCATED, text_tail

EVENTS_TAIL = 2 * 1024 * 1024
MESSAGE_LIMIT = 30000
MESSAGE_COUNT = 30


def public_messages(path):
    """Model text parts only; tool outputs and private reasoning are never shown as chat."""
    tail = text_tail(path, EVENTS_TAIL)
    messages = unique_texts(tail[TEXT])
    clipped = any(len(message[TEXT]) > MESSAGE_LIMIT for message in messages)
    shown = [clip(message) for message in messages[-MESSAGE_COUNT:]]
    truncated = tail[TRUNCATED] or clipped or len(messages) > MESSAGE_COUNT
    return {"items": shown, TRUNCATED: truncated}


def unique_texts(events):
    """Text parts in order; a repeated part ID is shown once."""
    seen = set()
    messages = []
    for line in events.splitlines():
        part, stamp = text_part(line)
        if part is None or part.get("id") in seen:
            continue
        if part.get("id"):
            seen.add(part["id"])
        messages.append(dict(text=part[TEXT], timestamp=stamp))
    return messages


def clip(message):
    """Bound one message for display."""
    return dict(message, text=message[TEXT][:MESSAGE_LIMIT])


def text_part(line):
    """The text part and timestamp of a text event, or (None, None)."""
    try:
        event = json.loads(line)
    except ValueError:
        return None, None
    if not isinstance(event, dict) or event.get("type") != TEXT:
        return None, None
    part = event.get("part", {})
    if not isinstance(part, dict):
        return None, None
    if not isinstance(part.get(TEXT), str):
        return None, None
    return part, event.get("timestamp")
