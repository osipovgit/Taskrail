"""Emit observed reads and strict results for workflow subprocess scenarios."""

import json
from pathlib import Path


def absolute(name, roots):
    if Path(name).is_absolute():
        return name
    alias, relative = name.split("/", 1)
    return str(Path(roots[alias]) / relative)


def attempt(args):
    """The server's record of this attempt, saved next to the request file."""
    request = Path(args[args.index("--file") + 1])
    return json.loads((request.parent / "stage.json").read_text())


def earlier_invalid(run, record):
    """An earlier attempt of the same stage returned an invalid result."""
    stages = json.loads((run / "run.json").read_text())["stages"]
    return any(
        entry["stage"] == record["stage"] and entry["status"] == "INVALID_RESULT"
        for entry in stages
        if entry["number"] < record["number"]
    )


def enrich(value, context, target, role, read_wrapper=False):
    """Fixture value with coverage and evidence; emits the cited read first."""
    evidence = []
    content = target.read_text()
    content = "\n".join(f"{number}: {line}" for number, line in enumerate(content.splitlines(), 1))
    if read_wrapper:
        content = f"<path>{target}</path>\n<type>file</type>\n<content>{content}\n</content>"
    print(
        json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "id": "source-read",
                    "callID": "source-read",
                    "tool": "read",
                    "state": {
                        "status": "completed",
                        "input": {"filePath": str(target)},
                        "output": content,
                        "metadata": {"truncated": False},
                    },
                },
            }
        ),
        flush=True,
    )
    evidence.append(
        {
            "id": "E1",
            "path": str(target),
            "line_start": 1,
            "line_end": 1,
        }
    )
    value.update(
        schema_version=1,
        evidence=evidence,
        unverified=value.get("unverified", []),
        blocking_gaps=value.get("blocking_gaps", []),
    )
    planned = role in ("planner", "plan-reviewer") and bool(
        value.get(
            "proposed_change_files",
            (context.get("plan") or {}).get("proposed_change_files", [str(target)]),
        )
    )
    outcome = "planned" if planned else "satisfied"
    if value["status"] == "BLOCKED":
        outcome = "gap"
    if value["status"] == "REQUEST_CHANGES":
        outcome = "contradicted"
    value["coverage"] = [
        {
            "id": entry["id"],
            "outcome": "deferred" if entry["kind"] == "runtime" else outcome,
            "evidence_ids": ["E1"],
            "explanation": "Fixture observation",
        }
        for entry in context["requirements"]
    ]
    if any(entry["kind"] == "runtime" for entry in context["requirements"]):
        value["unverified"] = ["Run the declared runtime scenario in the target environment"]
    for finding in value.get("findings", []):
        finding["criterion"] = context["requirements"][0]["id"]
    if role == "planner":
        value.setdefault("files_read", [str(target)])
        value.setdefault("proposed_change_files", [str(target)])
        for field in ("files_read", "proposed_change_files"):
            value[field] = [absolute(name, context["roots"]) for name in value[field]]
        value["steps"] = (
            [
                {
                    "id": "S1",
                    "action": "Return 2",
                    "files": value["proposed_change_files"],
                    "criteria": [entry["id"] for entry in context["requirements"]],
                    "checks": ["Static review"],
                    "depends_on": [],
                }
            ]
            if value["proposed_change_files"]
            else []
        )
    return value


CHECK_PREFIXES = ("Jenkins check:", "Server check:")


def plan_text(value, context):
    """The planner's JSON-shaped fixture value written as plan.md."""
    requirements = [entry["id"] for entry in context["requirements"]]
    steps = value.get("steps", [])
    names = {step["id"]: f"T{number}" for number, step in enumerate(steps, 1)}
    if value["status"] == "BLOCKED":
        decision = "blocked"
    elif not steps:
        decision = "no change"
    else:
        decision = "split" if len(steps) > 1 else "single"
    summary = (value.get("blocking_gaps") or [value.get("summary") or "Fixture plan"])[0]
    lines = [f"Decision: {decision}", f"Summary: {summary}"]
    lines += ["", "## Requirements"]
    evidence = {entry["id"]: entry for entry in value.get("evidence", [])}
    for entry in value.get("coverage", []):
        label = "R{}".format(requirements.index(entry["id"]) + 1)
        lines.append(f"- {label} → {outcome(entry, steps, names, evidence, value)}")
    for step in steps:
        lines += ["", "## {}: {}".format(names[step["id"]], step["action"].split(":")[0])]
        depends = ", ".join(names[name] for name in step.get("depends_on", [])) or "none"
        lines += [f"Depends on: {depends}", "Files: " + ", ".join(step["files"])]
        lines += ["Done when:", f"- {step['action']}", "Verify:"]
        lines += [f"- {check}" for check in step.get("checks") or ["Static review"]]
    checks = [entry for entry in value.get("unverified", []) if entry.startswith(CHECK_PREFIXES)]
    lines += ["", "## After the change", *[f"- {entry}" for entry in checks]]
    return "\n".join(lines) + "\n"


def outcome(entry, steps, names, evidence, value):
    """One requirement line's outcome."""
    kind = entry["outcome"]
    if kind == "planned":
        owners = [names[step["id"]] for step in steps if entry["id"] in step["criteria"]]
        if len(owners) > 1:
            owners = [f"{owner} [part {number}]" for number, owner in enumerate(owners, 1)]
        return ", ".join(owners)
    if kind in ("satisfied", "contradicted"):
        cited = [evidence[name] for name in entry["evidence_ids"] if name in evidence]
        spans = ["`{path}:{line_start}-{line_end}`".format(**item) for item in cited]
        return "{}: {}".format("done" if kind == "satisfied" else kind, ", ".join(spans))
    if kind == "deferred":
        return "runtime: " + (value.get("unverified") or ["Run the runtime check"])[0]
    return "gap: " + (value.get("blocking_gaps") or ["Missing input"])[0]


REVIEW_WORDS = {
    "satisfied": "done",
    "contradicted": "fails",
    "gap": "gap",
    "not_evaluated": "gap",
    "deferred": "later",
    "planned": "planned",
}


def review_text(value, context):
    """A reviewer's fixture value written as review.md."""
    requirements = [entry["id"] for entry in context["requirements"]]
    evidence = {entry["id"]: entry for entry in value.get("evidence", [])}
    problems = {entry["criterion"]: entry["evidence"] for entry in value.get("findings", [])}
    gaps = value.get("blocking_gaps") or ["Required input is missing"]
    lines = ["# Review", "Summary: {}".format(value.get("summary") or "Fixture review"), ""]
    lines.append("## Requirements")
    used = {name for entry in value.get("coverage", []) for name in entry["evidence_ids"]}
    unused = [name for name in evidence if name not in used]
    for index, entry in enumerate(value.get("coverage", [])):
        label = "R{}".format(requirements.index(entry["id"]) + 1)
        word = REVIEW_WORDS[entry["outcome"]]
        names = [*entry["evidence_ids"], *(unused if index == 0 else [])]
        cited = [evidence[name] for name in names if name in evidence]
        spans = ", ".join("`{path}:{line_start}-{line_end}`".format(**item) for item in cited)
        if word == "done":
            detail = spans
        elif word == "fails":
            problem = problems.get(entry["id"], entry.get("explanation") or "Fixture defect")
            detail = f"{spans} ({problem})"
        elif word == "gap":
            detail = gaps[0]
        elif word == "later":
            detail = (value.get("unverified") or ["Run the runtime check"])[0]
        else:
            lines.append(f"- {label}: planned: {spans}" if spans else f"- {label}: planned")
            continue
        lines.append(f"- {label}: {word}: {detail}")
    return "\n".join(lines) + "\n"
