"""Emit observed reads and strict results for workflow subprocess scenarios."""

import json
from pathlib import Path


def absolute(name, roots):
    if Path(name).is_absolute():
        return name
    alias, relative = name.split("/", 1)
    return str(Path(roots[alias]) / relative)


def enrich(value, context, target, prompt):
    role = context["stage"]
    evidence = []
    if "FORMAT REPAIR ONLY" not in prompt and "SYNTHESIS ONLY" not in prompt:
        content = target.read_text()
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
    elif role == "implementer":
        value["completed_steps"] = [step["id"] for step in context["plan"]["steps"]]
        manifest = json.loads((Path(context["task_file"]).parent / "manifest.json").read_text())
        import hashlib

        value["changed_files"] = []
        for name in context["allowed_files"]:
            path = Path(name)
            for alias, root in context["roots"].items():
                if Path(root) in path.parents:
                    key = alias + "/" + str(path.relative_to(root))
                    prior = (manifest.get(key) or "").rsplit(":", 1)[-1] or None
                    current = (
                        hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
                    )
                    if prior != current:
                        value["changed_files"].append(name)
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
        label = "R{0}".format(requirements.index(entry["id"]) + 1)
        lines.append(f"- {label} → {outcome(entry, steps, names, evidence, value)}")
    for step in steps:
        lines += ["", "## {0}: {1}".format(names[step["id"]], step["action"].split(":")[0])]
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
        spans = ["{path}:{line_start}-{line_end}".format(**item) for item in cited]
        return "{0}: {1}".format("done" if kind == "satisfied" else kind, ", ".join(spans))
    if kind == "deferred":
        return "runtime: " + (value.get("unverified") or ["Run the runtime check"])[0]
    return "gap: " + (value.get("blocking_gaps") or ["Missing input"])[0]
