"""Mode instructions from the run's task header flags, for browser and CLI tasks alike.

A run that changes code plans its Goal as tasks in plan.md. With Decision single the
same run implements them; with Decision split each task becomes its own run (see
plan_contract.splits), started in dependency order. Checks that must run after the
change are listed under `## After the change` with fixed prefixes, so the server can
run Jenkins validation and, after the operator confirms, server checks.
"""

from types import MappingProxyType

PLANNING_STAGES = frozenset(("planner", "plan-reviewer"))
TASKS = (
    "Plan the Goal as tasks. A task is one action: a single deliverable, with its own "
    "tests and the documentation it makes necessary, that one implementation run and one "
    "review can finish without compaction. Tasks are independent: one relies on another only through Depends "
    "on, and each owns at least one requirement or a scoped part of one. A task survives "
    "only if, with all its prerequisites done, it still has its own requirement and a "
    "non-empty change; fold it into its owner otherwise. Never plan a task that only runs "
    "checks or only updates documentation another task already owes. Two tasks may change "
    "the same file only with an explicit dependency ordering them and distinct behavior. "
    "A prerequisite may land unused "
    "(built, tested and documented) for a later task that wires it in."
)
CHECKS = (
    "List each check that must run after the change under ## After the change: 'Jenkins "
    "check: <server>/<job>: <parameters and expected result>' for a configured Jenkins job "
    "that validates the finished change, or 'Server check: <what to run and the expected "
    "result>' for a check on servers. Server checks run only after the operator confirms "
    "the changes; never change server state before that."
)
SPLIT = (
    "Decide split when the work is several such tasks: each runs as its own run with its "
    "own planning, implementation and review, so this run only plans; research only what "
    "you need to define and order the tasks, and each task run studies its own files."
)
ANSWER = "Write Decision: no change and no tasks, cover each requirement with done: or gap:, and put the answer in a ## Answer section."
RULES = MappingProxyType(
    {
        "decompose": f"Split into tasks. {TASKS} {SPLIT} {CHECKS}",
        "design": f"Design discussion: no edits. {ANSWER} The answer is a design document with the sections Context, Options, Trade-offs, Recommendation, Risks, Implementation outline and Open questions, grounded in cited source evidence. In a continued discussion, refine the earlier document according to the latest Goal.",
        "read_only": f"Answer only: no edits. {ANSWER} It holds the evidence-based answer.",
    }
)
CHANGE = (
    "Change code. {0} Decide single when the work is one task or cannot be cut into such "
    "tasks safely; this run then implements it. {1} {2}"
)
ATOMIC = (
    "This is one reviewed child task. Choose single with exactly one task, or no change "
    "when already satisfied. Never split again. Change only task_scope files. If the "
    "contract needs more files or cannot fit one session without compaction, choose "
    "blocked and explain the parent replanning required. The current contract and global "
    "constraints are supplied here. Consult only specific missing sections of the sealed "
    "parent-task.md when needed, never its full contents; implement only this child's criteria."
)


def render(config, stage):
    """The rule of the run's mode; a code change gets its planning rule while it plans."""
    if config.get("phase") == "task":
        return f"\nMode of this run. {ATOMIC}\n"
    if config.get("phase") == "integration":
        return (
            f"\nMode of this run. Independent integration review: no edits. {ANSWER} "
            "Verify the original goal and every acceptance criterion against the combined "
            "current source after all child tasks. Recheck interactions and regression risks; "
            "child success reports are reference data, not proof. Request required local "
            "diagnostics through LOCAL_REQUEST. Missing static acceptance evidence is a "
            "gap, never success. Explicit runtime checks remain deferred to their delivery phase.\n"
        )
    for flag, rule in RULES.items():
        if config.get(flag):
            return f"\nMode of this run. {rule}\n"
    if stage not in PLANNING_STAGES:
        return ""
    return "\nMode of this run. {0}\n".format(CHANGE.format(TASKS, SPLIT, CHECKS))
