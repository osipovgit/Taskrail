"""Advisory first reads may name a file or an exact range within it."""

import re

from taskrail.core import plan_citations
from taskrail.core.paths import absolute

PATH_ONLY = r"`[^`\n]+`|[^`:\s,;()*?\[\]{}]+"
READ_ITEM = re.compile("|".join((plan_citations.CITATION.pattern, PATH_ONLY)))
REFERENCE = re.compile(r"(.+?)(?::([1-9]\d*)(?:-([1-9]\d*))?)?")


def parse(entry, roots):
    """Read hints allow the same trailing explanations as evidence citations."""
    matches, explanation = plan_citations.parts(entry, syntax=READ_ITEM)
    return [window(span, roots) for span in matches], explanation


def window(span, roots):
    """An exact future source file, optionally narrowed to specific lines."""
    name, start, end = span
    if name.rsplit("/", 1)[-1] in {"", ".", ".."}:
        raise ValueError("A read hint must name a file")
    path = absolute(name, roots)
    if not path.is_absolute():
        raise ValueError("Read path needs a root alias")
    if start is None:
        return str(path)
    last = end or start
    if not 0 < int(start) <= int(last):
        raise ValueError("Invalid source line range")
    return f"{path}:{start}-{last}"


def split_hint(hint):
    """Separate a normalized file path from its optional numeric :line-range suffix."""
    match = REFERENCE.fullmatch(hint)
    if not match:
        return hint, ""
    return match[1], hint[match.end(1) :]


def scoped(hints, roots, extra):
    """Ignore pointers outside the preview directories before spending the read budget."""
    directories = (*roots.values(), *extra)
    for hint in hints:
        name, suffix = split_hint(hint)
        path = absolute(name, roots)
        if any(directory in path.parents for directory in directories):
            yield f"{path}{suffix}"
