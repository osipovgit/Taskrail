"""The task of a phase run: Jenkins validation, or server checks after confirmation."""

from types import MappingProxyType

from taskrail.application import worktree_isolation
from taskrail.core import prompt_texts
from taskrail.web import delivery_checks, epic_tasks, history, split_approvals
from taskrail.web.delivery_steps import CHECK_KEYS, SERVER, VALIDATION

TITLE_LIMIT = 160
TITLES = MappingProxyType({VALIDATION: "Jenkins validation", SERVER: "Server checks"})


def payload(run, state, name):
    """Task form fields of one phase run; the checks are its runtime requirements.

    Written checks become its deferred verification; selected recipes keep their typed
    criterion IDs.
    """
    draft = history.task_draft(run)
    title = "{} · {}".format(draft["title"], TITLES[name])
    written = delivery_checks.written(run, state)[CHECK_KEYS[name]]
    fields = dict(
        title=title[:TITLE_LIMIT],
        goal=prompt_texts.current(f"delivery.{name}"),
        criteria=prompt_texts.current("delivery.criteria"),
        verification="\n".join(written),
        constraints=draft["constraints"],
        split_context=brief(run, state, draft),
        roots=worktree_isolation.root_entries(state["roots"]),
        auto_approve=split_approvals.allows_all(run, draft),
        phase=name,
        check_parent=run.name,
    )
    if name == SERVER:
        fields["confirmed_change"] = run.name
    fields.update(typed_checks(run, state, name))
    return fields


def typed_checks(run, state, name):
    """Phase checks keep parent runtime identities instead of extracting labels again."""
    specs = state.get(delivery_checks.SPECS, [])
    selected = [spec for spec in specs if spec["phase"] == name]
    if not selected:
        return {}
    criteria = {criterion for entry in selected for criterion in entry["criteria"]}
    assigned = [entry for entry in state["requirements"] if entry["id"] in criteria]
    return dict(check_specs=selected, assigned_requirements=assigned, check_parent=run.name)


def brief(run, state, draft):
    """The overall goal and criteria and the files the change touched."""
    changed = ", ".join(changed_files(run, state)) or "none recorded"
    scope = prompt_texts.current("delivery.scope", run=run.name)
    lines = [scope, "", "Overall goal:", draft["goal"], ""]
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
