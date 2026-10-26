"""Keep validated form input separate from its human-readable task rendering."""

from taskrail.core import input_rendering, task_spec


def metadata(payload, form, roots, rendered):
    """The typed fields preserve user strings; empty optional fields use form defaults."""
    spec = task_spec.from_fields(original_fields(payload, form))
    body = rendered.partition("\n```\n")[2]
    spec["body"] = input_rendering.signature(body)
    lines = map(str.strip, form["verification"].splitlines())
    checks = list(filter(None, lines))
    return dict(roots=roots, verification=checks, task_spec=spec)


def original_fields(payload, form):
    """A nonempty user value retains its whitespace, including indentation."""
    original = {}
    for key, text in form.items():
        original[key] = payload.get(key) or text
    return original
