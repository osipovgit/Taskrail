"""A deterministic summary of long command output: size, severities, files and rules.

The model reads the summary instead of thousands of lines of lint, test or build
output and then opens only the windows it needs from the full output file.
"""

import re
from collections import Counter
from pathlib import Path

from taskrail.core import prompt_texts

FILE_MENTION = re.compile(r"([\w./-]+\.[A-Za-z0-9]{1,8}):\d+")
RULE = re.compile(r"\b([a-z][a-z0-9-]*\[[\w-]+\]|[A-Z]{1,4}\d{2,4}\b)")
SEVERITIES = ("error", "warning", "fail")
SHOWN = 10


def summary(outputs):
    """One digest per long output file, by stream name."""
    digests = []
    for name, location in outputs.items():
        digests.append(digest(name, Path(location)))
    return "\n".join(digests)


def digest(name, location):
    """Lines, severity mentions and the most mentioned files and rules of one output."""
    text = location.read_text(encoding="utf-8", errors="replace")
    lowered = text.casefold().splitlines()
    severities = mentions(lowered)
    lines = [f"Digest of {name} ({len(lowered)} lines, {location}): lines mentioning {severities}."]
    lines.append(f"Files most mentioned: {ranked(FILE_MENTION.findall(text))}")
    lines.append(f"Rules most mentioned: {ranked(RULE.findall(text))}")
    lines.append(prompt_texts.text("output.windows"))
    return "\n".join(lines)


def mentions(lines):
    """`count word` for each severity word, counting the lines that mention it."""
    counts = {word: sum(word in line for line in lines) for word in SEVERITIES}
    return ", ".join(f"{count} {word}" for word, count in counts.items())


def ranked(found):
    """`name (count)` of the most frequent entries, or none."""
    common = Counter(found).most_common(SHOWN)
    shown = [f"{entry} ({count})" for entry, count in common]
    return ", ".join(shown) or "none"
