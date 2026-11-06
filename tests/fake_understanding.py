"""Scripted input interpretation for subprocess regressions, never a model-quality oracle."""

import json

from fixture_blocks import is_label, spans


def execute(context, run, prompt, mode, emit):
    entries = []
    for field in context["task_fields"]:
        name, text = field["name"], field["text"]
        if isinstance(text, dict):
            text = "".join(text["text_chunks"])
        if name not in {"goal", "criteria", "constraints"}:
            continue
        for start, end in spans(text):
            quote = text[start:end]
            if is_label(quote):
                continue
            kind = "constraint" if name == "constraints" else "task"
            entries.append(dict(text=quote, kind=kind, sources=[dict(field=name, quote=quote)]))
    if mode == "understanding-invalid" and "final result was rejected" not in prompt:
        entries[0]["sources"][0]["quote"] = "An invented quote"
    if mode.startswith("input-revision-"):
        entries = [
            dict(text="Return 2.", kind="task", sources=[dict(field="goal", quote="Return 2.")])
        ]
        if context.get("feedback"):
            entries.append(
                dict(
                    text="Preserve the comment.",
                    kind="constraint",
                    sources=[dict(field="goal", quote="Preserve the comment.")],
                )
            )
    payload = dict(summary="Extract the fixture's explicit obligations", requirements=entries)
    (run / "understanding.json").write_text(json.dumps(payload, ensure_ascii=False))
    emit(json.dumps(dict(type="text", part=dict(messageID="understood", text="DONE"))))
    emit(
        json.dumps(
            dict(
                type="step_finish",
                part=dict(messageID="understood", reason="stop", tokens=dict(input=10, output=2)),
            )
        )
    )


def revision(run, emit):
    state = json.loads((run / "run.json").read_text())
    understood = [stage for stage in state["stages"] if stage["stage"] == "understanding"]
    if len(understood) != 1:
        return False
    response = dict(
        status="REINTERPRET_TASK",
        summary="The preservation constraint was omitted.",
        sources=[dict(field="goal", quote="Preserve the comment.")],
    )
    emit(
        json.dumps(
            dict(type="text", part=dict(messageID="revise-input", text=json.dumps(response)))
        )
    )
    emit(
        json.dumps(
            dict(
                type="step_finish",
                part=dict(messageID="revise-input", reason="stop", tokens=dict(input=10, output=2)),
            )
        )
    )
    return True
