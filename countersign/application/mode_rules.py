"""Mode instructions from the run's task header flags, for browser and CLI tasks alike.

A run that changes code plans its Goal as tasks: a small plan is implemented in the
same run, a larger one becomes one run per task (see plan_contract.splits). Checks
that must run after the change are named in unverified with fixed prefixes, so the
server can run Jenkins validation and, after the operator confirms, server checks.
"""

from types import MappingProxyType

PLANNING_STAGES = frozenset(("planner", "plan-reviewer"))
TASKS = (
    "Plan the Goal as tasks. A task is one focused, reviewable change with its code, "
    "tests and documentation: a few hundred changed lines and at most about ten files. "
    "A small goal is one task; plan several only when the work is larger, at most 8, "
    "ordered so each leaves the project working. Each plan step is one task: action "
    "'<short title>: <what it delivers>', the files it changes, the requirement IDs it "
    "covers as criteria, the earlier tasks it needs in depends_on and its acceptance checks."
)
CHECKS = (
    "List each check that must run after the change as its own entry in unverified, "
    "prefixed exactly 'Jenkins check: <server>/<job>: <parameters and expected result>' for "
    "a configured Jenkins job that validates the finished change, or 'Server check: <what "
    "to run and the expected result>' for a check on servers. Server checks run only after "
    "the operator confirms the changes; never change server state before that."
)
SPLIT_ONLY = (
    "Each task runs as its own run with its own planning, implementation and review, so "
    "this run only plans: research only what you need to define, order and size the tasks; "
    "each task run studies its own files. Plan review approves the split itself."
)
RULES = MappingProxyType(
    {
        "decompose": f"Split into tasks. {TASKS} {SPLIT_ONLY} {CHECKS}",
        "design": "Design discussion: no edits. Return empty steps and proposed_change_files. In summary write a design document in Markdown with the sections Context, Options, Trade-offs, Recommendation, Risks, Implementation outline and Open questions, grounded in quoted source evidence. In a continued discussion, refine the earlier document according to the latest Goal.",
        "read_only": "Answer only: no edits. Return empty steps and proposed_change_files with the evidence-based answer in summary.",
    }
)
CHANGE = (
    "Change code. {0} If all tasks together change at most {1} files, this run implements "
    "them. Otherwise: {2} {3}"
)


def render(config, stage):
    """The rule of the run's mode; a code change gets its planning rule while it plans."""
    for flag, rule in RULES.items():
        if config.get(flag):
            return f"\nMode of this run. {rule}\n"
    if stage not in PLANNING_STAGES:
        return ""
    change = CHANGE.format(TASKS, split_files(config), SPLIT_ONLY, CHECKS)
    return f"\nMode of this run. {change}\n"


def split_files(config):
    """A plan touching more files than one review allows runs one task per run."""
    return config.get("max_change_files") or DEFAULT_SPLIT_FILES


DEFAULT_SPLIT_FILES = 15
