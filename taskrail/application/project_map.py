"""A map of the declared roots for the planner, written once before planning.

It lists source files with their line counts and landmarks, without inferring their
relevance to the task. An index at the top gives the line range of each
section, and each root's part stays within its share of MAP_LIMIT characters.
"""

from functools import partial
from itertools import starmap

from taskrail.application import project_files
from taskrail.core import prompt_texts, protected_paths
from taskrail.core.files import atomic_write

NAME = "00-input/project-map.md"
MAP_LIMIT = 60000
LINE_LIMIT = 240


def prepare(run, roots, protected=protected_paths.DEFAULT_PATTERNS):
    """Write the map once per run; returns its path."""
    target = run / NAME
    if not target.exists():
        atomic_write(target, render(roots, protected).encode())
    return target


def render(roots, protected=protected_paths.DEFAULT_PATTERNS):
    """A neutral inventory: header, index and one section per declared root."""
    share = MAP_LIMIT // len(roots)
    section = partial(root_section, share=share, protected=protected)
    sections = list(starmap(section, roots.items()))
    return assembled(sections)


def root_section(alias, root, share, protected):
    """`## alias: root` and one line per file until the root's share is used."""
    names = project_files.listing(root, protected)
    lines = [f"## {alias}: {root}"]
    available = share - len(lines[0])
    for count, name in enumerate(names):
        if available < 0:
            lines.append(prompt_texts.text("map.more", count=len(names) - count))
            break
        lines.append(file_line(f"{alias}/{name}", root / name))
        available -= len(lines[-1])
    return lines


def file_line(shown, path):
    """`- path (n lines): landmarks`, without retaining file contents."""
    found = project_files.described(path)
    if found is None:
        return f"- {shown} (binary, large or unreadable)"
    count, marks = found
    detail = ": {}".format("; ".join(marks)) if marks else ""
    return f"- {shown} ({count} lines){detail}"[:LINE_LIMIT]


def assembled(sections):
    """The header, an index of the sections with their line ranges, then the sections."""
    header = prompt_texts.text("map.header").splitlines()
    index = index_lines(sections, len(header) + len(sections) + 4)
    body = ["\n".join(["", *part]) for part in sections]
    return "\n".join([*header, *index, *body, ""])


def index_lines(sections, start):
    """`## Index` and each section's title with its line range, from line start on."""
    index = ["", "## Index"]
    for section in sections:
        end = start + len(section) - 1
        title = section[0].removeprefix("## ")
        index.append(f"- {title} · lines {start}-{end}")
        start = end + 2
    return index
