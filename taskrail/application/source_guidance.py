"""Point explicit large JSON inputs at readable views before model research starts."""

from pathlib import Path

from taskrail.application import source_views, source_windows
from taskrail.core import protected_paths
from taskrail.core.paths import tool_paths

VIEW_LIMIT = 5


def inputs(config, plan, run):
    """Prepare only exact approved input paths, never discover files from task prose."""
    views = []
    scope = (config["roots"], run, protected_paths.patterns(config))
    paths = dict.fromkeys(
        source_path(reference, *scope) for reference in source_windows.requests(config, plan)
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
    match = source_windows.REFERENCE.fullmatch(tool_paths(reference, roots))
    if match and source_views.directory(run) in Path(match[1]).parents:
        return Path(match[1])
    return source_windows.source_path(match[1], roots, protected) if match else None


def prepared(path, run, roots):
    """A later reviewer receives the verified original identity of an existing view."""
    if source_views.directory(run) not in path.parents:
        return source_views.prepare(run, path, roots)
    try:
        return source_views.validate(run, path, roots)
    except ValueError:
        return None
