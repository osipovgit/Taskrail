"""A map of the declared roots for the planner, written once before planning.

It lists each source file with its line count and landmarks and points every
requirement at the files that name its distinctive words, so the planner reads where
the work is instead of exploring. An index at the top gives the line range of each
section, and each root's part stays within its share of MAP_LIMIT characters.
"""

from functools import partial
from itertools import starmap

from taskrail.application import project_files, requirement_hints
from taskrail.core import prompt_texts, protected_paths
from taskrail.infrastructure.agent_sync import atomic_write

NAME = "00-input/project-map.md"
MAP_LIMIT = 60000
LINE_LIMIT = 240
SEARCHED_SIZE = 200000
SEARCHED_FILES = 2000


def prepare(run, roots, requirements, protected=protected_paths.DEFAULT_PATTERNS):
    """Write the map once per run; returns its path."""
    target = run / NAME
    if not target.exists():
        atomic_write(target, render(roots, requirements, protected).encode())
    return target


def render(roots, requirements, protected=protected_paths.DEFAULT_PATTERNS):
    """The map: header, index, one section per root, then the requirement hints."""
    texts = {}
    share = MAP_LIMIT // len(roots)
    section = partial(root_section, texts=texts, share=share, protected=protected)
    sections = list(starmap(section, roots.items()))
    hints = requirement_hints.hint_lines(requirements, texts) or [prompt_texts.text("map.no_hints")]
    return assembled([*sections, ["## Requirement hints", *hints]])


def root_section(alias, root, texts, share, protected):
    """`## alias: root` and one line per file until the root's share is used."""
    names = project_files.listing(root, protected)
    lines = [f"## {alias}: {root}"]
    for count, name in enumerate(names):
        if sum(map(len, lines)) > share:
            remaining = len(names) - count
            lines.append(prompt_texts.text("map.more", count=remaining))
            break
        lines.append(file_line(f"{alias}/{name}", root / name, texts))
    return lines


def file_line(shown, path, texts):
    """`- path (n lines): landmarks`; a searchable text is kept for the hints."""
    found = project_files.described(path)
    if found is None:
        return f"- {shown} (binary, large or unreadable)"
    count, marks, text = found
    if len(text) <= SEARCHED_SIZE and len(texts) < SEARCHED_FILES:
        texts[shown] = text
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
