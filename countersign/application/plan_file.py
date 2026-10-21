"""The plan file a planner writes: its template, its instructions and its result.

plan.md lives in the run directory, so an interrupted or overflowing session leaves
it behind and the next attempt continues it. The planner may write only this file;
the server reads it, derives the plan result and names every problem by line.
"""

from countersign.application import project_map
from countersign.core import plan_document
from countersign.infrastructure.agent_sync import atomic_write

NAME = "plan.md"
REQUIREMENT_LINE = "- R{0} → <outcome>"
TEMPLATE = """# Plan
<!-- The request describes this format. Replace every <...>; keep the keys. -->
Decision: <split | single | no change | blocked>
Summary: <one or two sentences>

## Requirements
{0}

## T1: <short title>
Depends on: none
Files: <paths>
Done when:
- <observable result>
Verify:
- <check to run>
Notes:

## After the change
"""
FORMAT = """
PLAN FILE: your result is the Markdown file {0}, which already holds a template. Edit it with your edit tool while you work: write the Decision and the requirement lines early and refine them, so the plan survives an interrupted session. When it is complete, end your turn with the single word DONE; the server reads the file and returns each problem with its line. An executor request (GIT_REQUEST, LOCAL_REQUEST, ACTION_REQUEST, JENKINS_REQUEST) is still one JSON object as your entire final message.
- Decision: split (several independent tasks, each its own run), single (this run implements its tasks), no change (every requirement is already met) or blocked (a required input is missing).
- Summary: one or two sentences. An answer or design document goes in a ## Answer section instead, written as Markdown.
- ## Requirements: one line per requirement, R<n> → its outcome: the tasks that deliver it (T2; parts of one requirement name their scope: T1 [roles/ntp], T2 [roles/web]), done: <path>:<from>-<to> (lines you read that already meet it), runtime: <check> (a runtime requirement checked later) or gap: <the missing input>.
- One ## T<n>: <title> section per task: Depends on: (task IDs or none), Files: (paths it changes; mark new ones (new)), Done when: (observable results), Verify: (checks to run), optional Notes: (pointers for its implementer).
- ## After the change: optional lines 'Jenkins check: <server>/<job>: <parameters and expected result>' and 'Server check: <what to run and the expected result>'.
Paths are absolute or start with a root alias. Never copy source or requirement texts into the file; the server derives coverage, files, order and task runs from it.
PROJECT MAP: {1} lists every source file with its size and landmarks and points each requirement at the files that name it. Read its index first and start your research there instead of exploring.
Requirements, verbatim (use their labels in the plan file):
"""


def path(run):
    """Where the plan of a run is written."""
    return run / NAME


def prepare(run, requirements):
    """Write the template once; an existing plan is continued, never replaced."""
    target = path(run)
    if not target.exists():
        numbers = range(1, len(requirements) + 1)
        lines = "\n".join(REQUIREMENT_LINE.format(number) for number in numbers)
        atomic_write(target, TEMPLATE.format(lines).encode())
    return target


def grant(access, run, requirements):
    """Let the planner's profile read and write plan.md, and only that file."""
    target = prepare(run, requirements)
    access["writable"] = [*access["writable"], target]
    access["readable"].append(target)


def instructions(run, roots, requirements):
    """The format, the project map and the requirement labels in the planner's request.

    The map is written on the first request of the run.
    """
    listed = [label(number, entry) for number, entry in enumerate(requirements, 1)]
    text = FORMAT.format(path(run), project_map.prepare(run, roots, requirements))
    return "{0}{1}\n".format(text, "\n".join(listed))


def label(number, requirement):
    """R<n>. text, marked when it is checked at runtime."""
    kind = " (runtime)" if requirement["kind"] == "runtime" else ""
    return f"R{number}.{kind} {requirement['text']}"


def read_plan(run, requirements, roots):
    """The plan result of the written file; ValueError names its problems."""
    target = path(run)
    text = target.read_text(encoding="utf-8") if target.is_file() else ""
    return plan_document.payload(text, requirements, roots)


def labelled(message, requirements):
    """A validation message with requirement IDs replaced by their plan labels."""
    for number, entry in enumerate(requirements, 1):
        message = message.replace(entry["id"], f"R{number}")
    return message
