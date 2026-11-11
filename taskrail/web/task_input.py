"""Keep validated form input separate from its human-readable task rendering."""

from taskrail.core import input_rendering, task_spec

TITLE_WORDS = 80


def metadata(payload, form, roots, rendered):
    """Keep the original source fields verbatim, including omitted optional text."""
    spec = task_spec.from_fields(payload)
    body = rendered.partition("\n```\n")[2]
    spec["body"] = input_rendering.signature(body)
    lines = map(str.strip, form["verification"].splitlines())
    checks = list(filter(None, lines))
    return dict(roots=roots, verification=checks, task_spec=spec)


def display_title(goal, fallback=""):
    """The goal's first line, shortened at a word boundary for display."""
    lines = goal.strip().splitlines()
    line = lines[0].strip() if lines else fallback
    if len(line) <= TITLE_WORDS:
        return line
    return "{}...".format(line[:TITLE_WORDS].rsplit(" ", 1)[0])
