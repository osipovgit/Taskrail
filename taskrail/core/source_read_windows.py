"""Bound repair reads by source bytes as well as lines to avoid repeated clipping."""

MAX_BYTES = 12288
MAX_LINES = 200
WRAPPER_BYTES = 1024
LINE_PREFIX_BYTES = 32


def windows(lines):
    """Reserve envelope/footer and numbered-prefix space around exact UTF-8 source."""
    ranges = []
    size = WRAPPER_BYTES
    for number, line in sorted(lines.items()):
        size += len(line.encode("utf-8")) + LINE_PREFIX_BYTES
        if continues(ranges, number, size):
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
            size = WRAPPER_BYTES + len(line.encode("utf-8")) + LINE_PREFIX_BYTES
    return ranges


def continues(ranges, number, size):
    """A single oversized line stays explicit so feedback can direct it to a source view."""
    return (
        bool(ranges)
        and number == ranges[-1][1] + 1
        and number - ranges[-1][0] < MAX_LINES
        and size <= MAX_BYTES
    )
