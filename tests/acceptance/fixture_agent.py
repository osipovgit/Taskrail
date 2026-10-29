"""Scripted decisions for real controller stages; this fixture is not a model evaluation."""

import json
from pathlib import Path

from acceptance.corpus import path, write
from fake_contract import enrich, plan_text, review_text


def execute(context, role, args, emit):
    case = json.loads(Path(args[args.index("--scenario") + 1]).read_text())
    roots = context["roots"]
    planned = [str(path(name, roots)) for name in case["changes"]]
    target = path(case["evidence_path"], roots)
    if role == "implementer":
        allowed = context["allowed_files"]
        for name, content in case["changes"].items():
            if str(path(name, roots)) in allowed:
                write(path(name, roots), content)
        if case.get("fault") == "scope":
            write(path("service/notes.txt", roots), "Unexpected alteration\n")
    value = dict(status="APPROVE", summary=case["summary"])
    if role == "planner":
        value.update(status="PLAN_READY", files_read=[str(target)], proposed_change_files=planned)
    elif role == "implementer":
        value["status"] = "IMPLEMENTED"
    value = enrich(value, context, target, role)
    run = Path(context["task_file"]).parent.parent
    if role == "planner":
        for step in value["steps"]:
            step.update(action=case["goal"], checks=["Inspect the scenario acceptance oracle"])
        if case["mode"] == "split":
            value["steps"] = [
                dict(
                    value["steps"][0],
                    id=f"S{number}",
                    action=f"Update timeout in {Path(name).name}",
                    files=[name],
                    depends_on=[f"S{number - 1}"] if number > 1 else [],
                )
                for number, name in enumerate(planned, 1)
            ]
        planned_text = plan_text(value, context)
        if case.get("answer"):
            planned_text += "\n## Answer\n" + case["answer"].replace("{source}", str(target)) + "\n"
        (run / "plan.md").write_text(planned_text)
        response = "DONE"
    elif role == "implementer":
        response = "DONE: " + value["summary"]
    else:
        (run / "review.md").write_text(review_text(value, context))
        response = "DONE"
    emit(json.dumps(dict(type="text", part=dict(id="result", messageID="msg1", text=response))))
    emit(
        json.dumps(
            dict(
                type="step_finish",
                part=dict(
                    id="finish", messageID="msg1", reason="stop", tokens=dict(input=10, output=2)
                ),
            )
        )
    )
