"""Large follow-up history: a bounded excerpt in the prompt, every turn in a run file.

task.md stays verbatim and complete. When its conversation history is larger than
INLINE_BYTES, a stage prompt carries the current task, the latest earlier turn's goal
and summary, and the path of history.md (see history_index).
"""

import json

from countersign.application.history_index import HistoryFile, section_lines, text_of
from countersign.core import requirements
from countersign.infrastructure.agent_sync import atomic_write

MARKER = f"{requirements.HISTORY}\n"
INLINE_BYTES = 24000
EXCERPT_CHARS = 2000
FILE_NAME = "00-input/history.md"
CLIPPED = " [clipped; the complete text is in the history file]"
NOTE = (
    "The {0} earlier turns ({1} bytes) are too large to repeat here. They are in {2}. "
    "First read lines 1-{3} of that file: an index of the turns with the line ranges of "
    "their goal, summary, task, conclusions and diff. Then read only the turns and sections "
    "you need, at most 200 lines at a time; never read the file whole. The latest earlier "
    "turn, with long fields clipped:\n"
)


def prompt_task(task_text, run):
    """The task as a stage prompt shows it: unchanged unless its history is large."""
    current, _, encoded = task_text.partition(MARKER)
    if size(encoded) <= INLINE_BYTES:
        return task_text
    turns = decoded_turns(encoded)
    if not turns:
        return task_text
    return f"{current}{MARKER}{reference(turns, encoded, run)}"


def reference(turns, encoded, run):
    """Write history.md; the prompt names it and its index and shows the latest turn."""
    path = run / FILE_NAME
    history = HistoryFile(turns)
    atomic_write(path, "\n".join(history.lines()).encode("utf-8"))
    note = NOTE.format(len(turns), size(encoded), path, history.index_end)
    return f"{note}{excerpt(turns[-1])}\n"


def decoded_turns(encoded):
    """The server-written list of turns, or None when the section is something else."""
    try:
        turns = json.loads(encoded)
    except ValueError:
        return None
    if not isinstance(turns, list):
        return None
    if all(isinstance(turn, dict) for turn in turns):
        return turns
    return None


def excerpt(turn):
    """The run, goal and summary of one turn, each clipped to EXCERPT_CHARS."""
    lines = ["### Run {}".format(turn.get("run", ""))]
    lines.extend(section_lines("Goal", clipped(turn.get("goal"))))
    lines.extend(section_lines("Summary", clipped(turn.get("summary"))))
    return "\n".join(lines)


def clipped(field):
    """Excerpt text, marked when it is shortened."""
    text = text_of(field)
    if len(text) <= EXCERPT_CHARS:
        return text
    return text[:EXCERPT_CHARS] + CLIPPED


def size(text):
    """UTF-8 bytes, the unit of the inline limit."""
    return len(text.encode("utf-8"))
