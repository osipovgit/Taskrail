"""Changes made outside a split's tasks before a task starts.

They never stop the task. The implementer reads them first, because its work may
already be done there or it may need to change those files too, and the task's report
and the integration review name them.
"""

from pathlib import Path

from countersign.core import prompt_texts

KEY = "outside_changes"
LISTED = 40
EXPECTED = "expected"
GIT = "git_before"
BULLET = "- {0}"


class Drift:
    """Files and Git state that changed between points of a split's chain."""

    def __init__(self):
        """Nothing changed outside the tasks yet."""
        self.files = set()
        self.git = False

    def between(self, before, after):
        """Add what differs between two points: {expected, git_before} each."""
        old, new = before[EXPECTED], after[EXPECTED]
        for name in old.keys() | new.keys():
            if old.get(name) != new.get(name):
                self.files.add(name)
        self.git = self.git or before[GIT] != after[GIT]

    def summary(self):
        """Sorted alias paths and whether Git changed; None when nothing changed."""
        if not self.files and not self.git:
            return None
        return dict(files=sorted(self.files), git=self.git)


def announce(workflow, outside):
    """Record the changes and add them to the implementer's first request."""
    workflow.state[KEY] = outside
    roots = workflow.config["roots"]
    files = [absolute(roots, name) for name in outside["files"]]
    git = " {}".format(prompt_texts.text("note.outside_git")) if outside["git"] else ""
    note = prompt_texts.text("note.outside_changes", files=listed(files), git=git)
    feedback = workflow.flow.get("feedback") or {}
    workflow.flow["feedback"] = dict(feedback, **{KEY: note})


def listed(files):
    """At most LISTED names; the report keeps the complete list."""
    shown = ", ".join(files[:LISTED]) or "none"
    more = len(files) - LISTED
    if more > 0:
        shown = "{} {}".format(shown, prompt_texts.text("note.outside_more", count=more))
    return shown


def absolute(roots, name):
    """An alias path as the absolute path the implementer edits."""
    alias, _, relative = name.partition("/")
    if alias not in roots:
        return name
    return str(Path(roots[alias]) / relative)


def integration_note(files):
    """The suffix of a task line in the integration review, or nothing."""
    if not files:
        return ""
    shown = ", ".join(files[:LISTED])
    return "; {}".format(prompt_texts.text("integration.outside", files=shown))


def report_lines(state):
    """The report section of a task that found changes made outside the split's tasks."""
    outside = state.get(KEY)
    if not outside:
        return []
    lines = ["", "## Changed outside this task", ""]
    lines.append(
        "Changed by the operator or another tool, not by the tasks of this split, before "
        "this task started; changes.diff may include these edits."
    )
    lines.append("")
    lines += [BULLET.format(name) for name in outside["files"]]
    if outside["git"]:
        lines.append("- Git state (commits, branch or index) also changed.")
    return lines
