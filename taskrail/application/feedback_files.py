"""Line-readable model inputs. Long feedback stays complete on disk."""

import json

from taskrail.core import prompt_texts

CONTEXT_LINE_LIMIT = 800
CHUNK_SIZE = 128
INLINE_CHARS = 6000


def readable_context(payload):
    """Preserve complete text without exceeding opencode's per-line read limit."""
    if (
        isinstance(payload, str)
        and len(json.dumps(payload, ensure_ascii=False).encode()) > CONTEXT_LINE_LIMIT
    ):
        offsets = range(0, len(payload), CHUNK_SIZE)
        chunks = [payload[offset : offset + CHUNK_SIZE] for offset in offsets]
        return {"text_chunks": chunks}
    if isinstance(payload, dict):
        return {key: readable_context(entry) for key, entry in payload.items()}
    if isinstance(payload, list):
        return [readable_context(entry) for entry in payload]
    return payload


def context_json(payload):
    """Context as JSON with one-space indentation: one value per line, few spaces."""
    return json.dumps(readable_context(payload), ensure_ascii=False, indent=1)


def validation(folder, message):
    """Publish the complete error set in pageable lines when it outgrows inline feedback."""
    lines = message.splitlines()
    longest = max(map(len, lines), default=0)
    if len(message) < INLINE_CHARS and longest <= CONTEXT_LINE_LIMIT:
        return message
    target = folder / "validation.json"
    rendered = context_json(message)
    target.write_text(rendered, encoding="utf-8")
    return prompt_texts.text("feedback.file", path=target, lines=len(rendered.splitlines()))


def findings(folder, feedback):
    """Both the writer and the next reviewer get the same complete record."""
    target = folder / "findings.json"
    text = context_json(feedback)
    target.write_text(f"{text}\n", encoding="utf-8")
    return dict(
        findings_file=str(target),
        lines=len(text.splitlines()),
        instruction=prompt_texts.text("feedback.review_file"),
    )
