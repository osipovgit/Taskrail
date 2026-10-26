"""Exercise incomplete report reads and exact, same-session evidence repair."""

import json
import re
from pathlib import Path


def report_result(context, prompt, header, emit):
    """A planner first cites clipped reports, then follows the server's precise feedback."""
    root = Path(context["roots"]["project"])
    run = Path(context["task_file"]).parent.parent
    plan = run / "plan.md"
    text = root / "issues.txt"
    raw = root / "report.json"
    claims = [dict(id="E1", path=str(text), line_start=1, line_end=1045)]
    if context["stage"] == "planner":
        view = re.search(r"available at (.+) \((\d+) lines\)", prompt)
        if view:
            assert "Evidence E1" in prompt and "Evidence E2" in prompt
            source = Path(view[1])
            assert header["permission"]["read"].get(str(source.parent) + "/*") == "allow"
            for offset in range(201, 1046, 200):
                observed(text, offset, 200, emit)
            observed(source, 1, 7, emit)
            claims.append(dict(id="E2", path=str(source), line_start=2, line_end=6))
        else:
            observed(text, 1, 200, emit)
            observed(raw, 1, 1, emit, clip=True)
            claims.append(dict(id="E2", path=str(raw), line_start=1, line_end=1))
        observed(plan, 1, 200, emit)
        references = ", ".join("{path}:{line_start}-{line_end}".format(**claim) for claim in claims)
        lines = ["Decision: no change", "Summary: Report reviewed", "## Requirements"]
        lines += [
            f"- R{number} → done: {references}"
            for number in range(1, len(context["requirements"]) + 1)
        ]
        plan.write_text("\n".join(lines) + "\n")
        response = "DONE"
    else:
        source = Path(re.search(r", (.+):2-6", plan.read_text())[1])
        for offset in range(1, 1046, 200):
            observed(text, offset, 200, emit)
        observed(source, 1, 7, emit)
        claims.append(dict(id="E2", path=str(source), line_start=2, line_end=6))
        response = json.dumps(review(context, claims))
    for kind, part in (
        ("text", dict(text=response)),
        ("step_finish", dict(reason="stop", tokens=dict(input=100, output=10))),
    ):
        part.update(id=kind, messageID="final")
        emit(json.dumps(dict(type=kind, part=part, sessionID="ses1")), flush=True)


def observed(path, offset, limit, emit, clip=False):
    """Only returned rows, including the deliberately clipped JSON prefix, enter the trace."""
    rows = path.read_text().splitlines()[offset - 1 : offset + limit - 1]
    output = "\n".join(f"{number}:{line}" for number, line in enumerate(rows, offset))
    if clip:
        output = output[:1500] + "... (line truncated)"
    state = dict(
        status="completed",
        input=dict(filePath=str(path), offset=offset, limit=limit),
        output=f"<path>{path}</path>\n<type>file</type>\n<content>{output}\n</content>",
        metadata=dict(truncated=clip),
    )
    identity = f"{path.name}-{offset}"
    part = dict(id=identity, callID=identity, tool="read", state=state)
    emit(json.dumps(dict(type="tool_use", part=part)), flush=True)


def review(context, claims):
    """Independent reviewer reaches the same sources through the real permission profile."""
    cited = ["{path}:{line_start}-{line_end}".format(**claim) for claim in claims]
    return dict(
        schema_version=2,
        summary="Observed reports match the answer",
        outcomes=[
            dict(requirement=entry["id"], result="satisfied", evidence=cited)
            for entry in context["requirements"]
        ],
        findings=[],
        missing_inputs=[],
    )
