"""The task of a phase run: Jenkins validation, or server checks after confirmation."""

from types import MappingProxyType

from countersign.application import worktree_isolation
from countersign.interactions import approval_policy
from countersign.web import epic_tasks, history
from countersign.web.delivery_steps import CHECK_KEYS, SERVER, VALIDATION

TITLE_LIMIT = 160
TITLES = MappingProxyType({VALIDATION: "Jenkins validation", SERVER: "Server checks"})
GOALS = MappingProxyType(
    {
        VALIDATION: "Validate the finished change with the Jenkins checks below. Start each build through JENKINS_REQUEST, then read its status, console and test results, and report whether the change passed. Do not change files.",
        SERVER: "The operator confirmed the finished change. Run the server checks below through ACTION_REQUEST, one exact action per check, and report what each observed. Change server state only as far as a check requires. Do not change files.",
    }
)
CRITERIA = "Every check below ran and its observed result is reported, or the reason it could not run is reported."
SCOPE = "This run checks a finished code change (run {0}); it changes no files."


def payload(run, state, name, checks):
    """Task form fields of one phase run; the checks are its runtime requirements."""
    draft = history.task_draft(run)
    title = "{0} · {1}".format(draft["title"], TITLES[name])
    fields = dict(
        title=title[:TITLE_LIMIT],
        goal=GOALS[name],
        criteria=CRITERIA,
        verification="\n".join(checks[CHECK_KEYS[name]]),
        constraints=draft["constraints"],
        split_context=brief(run, state, draft),
        roots=worktree_isolation.root_entries(state["roots"]),
        auto_approve=approval_policy.at_start(run, draft),
        phase=name,
    )
    if name == SERVER:
        fields["confirmed_change"] = run.name
    return fields


def brief(run, state, draft):
    """The overall goal and criteria and the files the change touched."""
    changed = ", ".join(changed_files(run, state)) or "none recorded"
    lines = [SCOPE.format(run.name), "", "Overall goal:", draft["goal"], ""]
    lines.extend(["Overall acceptance criteria:", draft["criteria"], ""])
    lines.append(f"Changed files: {changed}")
    return "\n".join(lines)


def changed_files(run, state):
    """Files changed by the run itself, or by every task run of a split."""
    if state.get("status") != epic_tasks.READY:
        return list(state.get("changed_files", []))
    files = []
    for task in epic_tasks.tasks(run, state):
        files.extend(name for name in task["changed_files"] if name not in files)
    return files
