"""Point explicit large JSON inputs at readable views before model research starts."""

from pathlib import Path

from taskrail.application import source_views, source_windows
from taskrail.core import protected_paths, read_hints

VIEW_LIMIT = 5


def inputs(config, plan, run):
    """Prepare only exact approved input paths, never discover files from task prose."""
    views = []
    scope = (config["roots"], run, protected_paths.patterns(config))
    paths = dict.fromkeys(
        source_path(reference, *scope)
        for reference in source_windows.requests(config, plan, (source_views.directory(run),))
    )
    for path in filter(None, paths):
        view = prepared(path, run, config["roots"])
        if view:
            views.append({key: view[key] for key in ("source_path", "path", "lines")})
        if len(views) == VIEW_LIMIT:
            break
    return views


def source_path(reference, roots, run, protected):
    """Resolve a source reference under the same access rules as source packets."""
    path = Path(read_hints.split_hint(reference)[0])
    if source_views.directory(run) in path.parents:
        return path
    return source_windows.source_path(path, roots, protected)


def prepared(path, run, roots):
    """A later reviewer receives the verified original identity of an existing view."""
    if source_views.directory(run) not in path.parents:
        return source_views.prepare(run, path, roots)
    try:
        return source_views.validate(run, path, roots)
    except ValueError:
        return None
