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
            "quote": target.read_text().splitlines()[0],
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
