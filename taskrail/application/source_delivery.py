"""Bound source delivery bytes and retain only ranges actually placed in a prompt."""

import json

from taskrail.application import evidence
from taskrail.core.files import atomic_json

PACKET_BYTES = 4000
SOURCE_PATH = "path"
LINES = "lines"


def public(packet):
    """Hashes remain internal; the model needs handles, canonical paths and exact lines."""
    return [{key: entry[key] for key in ("handle", SOURCE_PATH, LINES)} for entry in packet]


def append(packet, entry):
    """Try the full window, then bisect for the longest prefix fitting this packet."""
    rows = list(novel_lines(packet, entry).items())
    position = len(packet) + 1
    entry["handle"] = f"S{position}"
    lower, upper = 0, len(rows)
    count = upper
    while lower < upper:
        entry[LINES] = dict(rows[:count])
        if fits(packet, entry):
            lower = count
        else:
            upper = count - 1
        count = (lower + upper + 1) // 2
    entry[LINES] = dict(rows[:count])
    if count:
        packet.append(entry)


def fits(packet, entry):
    """Measure exactly the serialized public representation sent to the model."""
    proposed = public([*packet, entry])
    rendered = json.dumps(proposed, ensure_ascii=False, indent=2)
    return len(rendered.encode()) <= PACKET_BYTES


def novel_lines(packet, entry):
    """Do not spend context twice on the same current source position."""
    previous = [old for old in packet if old[SOURCE_PATH] == entry[SOURCE_PATH]]
    copied = {number for old in previous for number in old[LINES]}
    unseen = dict(entry[LINES])
    for number in copied:
        unseen.pop(number, None)
    return unseen


def retain(run, target, packet):
    """Retain reusable discovery; session delivery alone can authorize citation evidence."""
    index = evidence.load_index(run, evidence.OBSERVATIONS)
    numbered = enumerate(packet, 1)
    delivered = [observation(entry, target, position) for position, entry in numbered]
    index[evidence.RECORDS].extend(
        record for record in delivered if record not in index[evidence.RECORDS]
    )
    atomic_json(run / evidence.OBSERVATIONS, index)


def observation(entry, target, position):
    """Use the same exact numbered line protocol as attributed model source reads."""
    lines = entry[LINES].items()
    output = "\n".join(f"{number}: {line}" for number, line in lines)
    return dict(
        tool="source_packet",
        input=source_input(entry),
        output=output,
        source_sha256=entry["source_sha256"],
        source_event=str(target),
        event_line=position,
        call_id=f"source-packet-{position}",
        original_chars=len(output),
        output_clipped=False,
        upstream_truncated=False,
    )


def source_input(entry):
    """Distinct delivered windows must survive the shared read-observation deduplicator."""
    positions = sorted(map(int, entry[LINES]))
    count = positions[-1] - positions[0] + 1
    return dict(filePath=entry[SOURCE_PATH], offset=positions[0], limit=count)
