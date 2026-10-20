"""Mode instructions from the run's task header flags, for browser and CLI tasks alike."""

from types import MappingProxyType

# Precedence: a split is never read-only; a design discussion is also read-only.
RULES = MappingProxyType(
    {
        "decompose": "Split into tasks: plan the whole Goal as at most 8 sequential tasks (one is fine for a small goal); nothing is edited in this run. Each plan step is one task that a later, separate run plans again, implements and reviews on its own. Write its action as '<short title>: <what the task delivers>', list the files it changes, the requirement IDs it covers as criteria, the earlier tasks it needs in depends_on and its acceptance checks. Keep every task small enough for one focused review (a few hundred changed lines, about ten files). Order tasks so each leaves the project working. Plan review approves the split itself; approval ends this run with the tasks ready.",
        "design": "Design discussion: no edits. Return empty steps and proposed_change_files. In summary write a design document in Markdown with the sections Context, Options, Trade-offs, Recommendation, Risks, Implementation outline and Open questions, grounded in quoted source evidence. In a continued discussion, refine the earlier document according to the latest Goal.",
        "read_only": "Answer only: no edits. Return empty steps and proposed_change_files with the evidence-based answer in summary.",
    }
)


def render(config):
    """The rule of the run's mode, or nothing for a task that changes code."""
    for flag, rule in RULES.items():
        if config.get(flag):
            return f"\nMode of this run. {rule}\n"
    return ""
