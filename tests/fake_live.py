"""Subprocess fixture: CLI, installed profiles and JSON events, not a real model."""

import builtins
import json
import os
import sys
import time
import uuid
from pathlib import Path

from fake_contract import enrich, plan_text

args = sys.argv[1:]
if "--version" in args:
    print("1.0.0")
    sys.exit(0)
profiles = Path(args[args.index("--profiles") + 1])
mode = args[args.index("--mode") + 1]
if "agent" in args:
    for path in sorted(profiles.glob("countersign-*.md")):
        header = json.loads(path.read_text().split("---")[1])
        rules = []
        for permission, value in header["permission"].items():
            for pattern, action in value.items() if isinstance(value, dict) else [("*", value)]:
                rules.append(dict(permission=permission, pattern=pattern, action=action))
        if mode == "unsafe":
            rules.append(dict(permission="bash", pattern="*", action="allow"))
        print(path.stem + " (primary)\n" + json.dumps(rules))
    sys.exit(0)
original_print = builtins.print
turn_id = uuid.uuid4().hex


def print(*items, **kwargs):
    rewritten = []
    for item in items:
        try:
            event = json.loads(item)
        except (ValueError, TypeError):
            rewritten.append(item)
            continue
        if isinstance(event, dict) and "type" in event:
            event.setdefault("sessionID", "ses1")
            part = event.get("part", {})
            for field in ("id", "messageID", "callID"):
                if field in part:
                    part[field] = turn_id + part[field]
            item = json.dumps(event)
        rewritten.append(item)
    original_print(*rewritten, **kwargs)


agent = args[args.index("--agent") + 1]
prompt = Path(args[args.index("--file") + 1]).read_text()
saved_context = profiles / "fixture-context.json"
if "Context:\n" in prompt:
    context, _ = json.JSONDecoder().raw_decode(prompt.split("Context:\n", 1)[1])
    saved_context.write_text(json.dumps(context))
else:
    context = json.loads(saved_context.read_text())
header = json.loads((profiles / (agent + ".md")).read_text().split("---")[1])
if "FORMAT REPAIR ONLY" not in prompt and "SYNTHESIS ONLY" not in prompt:
    for file in [Path(args[args.index("--file") + 1]), Path(context["task_file"])] + (
        [Path(context["diff_file"])] if context.get("diff_file") else []
    ):
        assert header["permission"]["read"].get(str(file)) == "allow", str(file)
        assert header["permission"]["external_directory"].get(str(file.parent) + "/*") == "allow", (
            str(file.parent)
        )
root = Path(context["roots"]["project"])
target = root / ("Jenkinsfile" if mode == "jenkins" else "hello.py")
role = context["stage"]
if mode in {"git-actions", "git-denied"}:
    journal = Path(context["task_file"]).parent.parent / "git-execution.json"
    git_jobs = json.loads(journal.read_text()) if journal.exists() else []
    request_args = None
    if role == "planner" and not git_jobs:
        request_args = ["log", "-3", "--format=%H %s", "--", "."]
        if mode == "git-denied":
            request_args = ["log", "--output=/tmp/must-not-write"]
    if role == "implementer" and mode == "git-actions" and len(git_jobs) == 1:
        revision = (root / ".git/refs/heads/main").read_text().strip()
        request_args = ["revert", "--no-edit", revision]
    if request_args:
        request = dict(
            schema_version=1,
            status="GIT_REQUEST",
            root=str(root),
            argv=request_args,
            reason="Fixture task needs history and revert",
        )
        for event, part in [
            ("text", dict(text=json.dumps(request))),
            ("step_finish", dict(reason="stop", tokens={"input": 10, "output": 2})),
        ]:
            part.update(messageID="msg1", id=event)
            print(json.dumps(dict(type=event, part=part, sessionID="ses1")))
        sys.exit(0)
if mode == "ssh-action" and role == "planner" and "Ticket " not in prompt:
    action = dict(
        targets=["server-a"],
        script="uname -a\n",
        files={},
        reason="Inspect kernel",
        timeout_seconds=30,
    )
    request = dict(schema_version=1, status="ACTION_REQUEST", action=action)
    for event, part in [
        ("text", dict(text=json.dumps(request))),
        ("step_finish", dict(reason="stop", tokens={"input": 10, "output": 2})),
    ]:
        part.update(messageID="msg1", id=event)
        print(json.dumps(dict(type=event, part=part, sessionID="ses1")))
    sys.exit(0)
if (mode == "review-timeout" and role == "reviewer") or (
    mode == "planner-timeout" and role == "planner"
):
    time.sleep(5)
if mode in ("review-denied-once", "review-denied-always") and role == "reviewer":
    if mode == "review-denied-always" or "--session" not in args:
        print(
            json.dumps(
                dict(
                    type="tool_use",
                    part=dict(
                        tool="grep",
                        state=dict(
                            status="error",
                            input=dict(path="/wrong/admin/ci-pipelines", pattern="build"),
                            error="PermissionDeniedError",
                        ),
                    ),
                )
            ),
            flush=True,
        )
        sys.exit(0)
if mode in ("parent-once", "parent-twice") and role == "plan-reviewer":
    if mode == "parent-twice" or "--session" not in args:
        print(
            json.dumps(
                dict(
                    type="tool_use",
                    part=dict(
                        id="denied",
                        tool="grep",
                        callID="call-denied",
                        state=dict(
                            status="error",
                            input=dict(path=str(root.parent), pattern="build"),
                            error="PermissionDeniedError",
                        ),
                    ),
                )
            ),
            flush=True,
        )
        sys.exit(0)
if mode == "many-calls" and role == "planner":
    for index in range(350):
        print(
            json.dumps(
                dict(
                    type="tool_use",
                    part=dict(
                        id=f"many-{index}",
                        callID=f"many-{index}",
                        tool="glob",
                        state=dict(
                            status="completed",
                            input=dict(path=str(root), pattern="*.py"),
                            output=str(target),
                        ),
                    ),
                )
            ),
            flush=True,
        )
if mode == "missing-read" and role == "planner":
    missing = root / "tasks" / "main.yaml"
    print(
        json.dumps(
            dict(
                type="tool_use",
                part=dict(
                    id="missing-source",
                    tool="read",
                    state=dict(
                        status="error",
                        input=dict(filePath=str(missing)),
                        error="Error: File not found: " + str(missing),
                    ),
                ),
            )
        ),
        flush=True,
    )
if mode == "offset-recovered" and role == "planner":
    print(
        json.dumps(
            dict(
                type="tool_use",
                part=dict(
                    id="wrong-offset",
                    tool="read",
                    state=dict(
                        status="error",
                        input=dict(filePath=str(target), offset=1377),
                        error="Error: Offset 1377 is out of range for this file (3 lines)",
                    ),
                ),
            )
        ),
        flush=True,
    )
    numbered = "\n".join(
        "%d:%s" % (i, line) for i, line in enumerate(target.read_text().splitlines(), 1)
    )
    print(
        json.dumps(
            dict(
                type="tool_use",
                part=dict(
                    id="corrected-offset",
                    callID="corrected",
                    tool="read",
                    state=dict(
                        status="completed",
                        input=dict(filePath=str(target), offset=1),
                        output=numbered + "\n(End of file - total 3 lines)",
                        metadata=dict(truncated=False),
                    ),
                ),
            )
        ),
        flush=True,
    )
if role == "plan-reviewer":
    for entry in context.get("source_packet", []):
        name = entry["path"]
        assert Path(name).is_absolute(), name
        Path(name).read_bytes()
if role == "implementer" and "FORMAT REPAIR ONLY" in prompt:
    header = json.loads((profiles / (agent + ".md")).read_text().split("---")[1])
    assert header["permission"]["edit"] == "deny", header["permission"]["edit"]
elif role == "implementer":
    assert all(Path(name).is_absolute() for name in context["allowed_files"])
    header = json.loads((profiles / (agent + ".md")).read_text().split("---")[1])
    for name in context["allowed_files"]:
        relative = os.path.relpath(name, root)
        assert header["permission"]["edit"].get(relative) == "allow", relative
if mode == "denied" and role == "plan-reviewer":
    print(
        json.dumps(
            dict(
                type="tool_use",
                part=dict(
                    id="denied",
                    tool="read",
                    callID="call-denied",
                    state=dict(
                        status="error",
                        input=dict(filePath="/outside/skills/SKILL.md"),
                        error='PermissionDeniedError({"_tag":"PermissionDeniedError"})',
                    ),
                ),
            )
        )
    )
if mode in ("read-retry", "timeout-then-invalid", "timeout-evidence") and role == "planner":
    marker = profiles / ".retry-marker"
    if not marker.exists():
        marker.write_text("1")
        if mode == "timeout-evidence":
            print(
                json.dumps(
                    dict(
                        type="tool_use",
                        part=dict(
                            id="read-one",
                            callID="read-one",
                            tool="read",
                            state=dict(
                                status="completed",
                                input=dict(filePath=str(target)),
                                output="\n".join(
                                    f"{number}: {line}"
                                    for number, line in enumerate(
                                        target.read_text().splitlines(), 1
                                    )
                                ),
                                metadata=dict(truncated=False),
                            ),
                        ),
                    )
                ),
                flush=True,
            )
            time.sleep(5)
        if mode == "timeout-then-invalid":
            time.sleep(5)
        sys.exit(0)
if mode == "timeout-evidence" and role == "planner":
    evidence = Path(args[args.index("--file") + 1]).parent / "recovery.md"
    assert "return 1" in evidence.read_text()
    assert "RECOVERY:" in prompt
    assert header["permission"]["read"][str(evidence)] == "allow"
    assert header["permission"]["external_directory"][str(evidence.parent) + "/*"] == "allow"
if (
    mode in ("invalid-once", "timeout-then-invalid", "format-unavailable")
    and role == "planner"
    and "Previous response was invalid" not in prompt
):
    value = dict(status="PLAN_READY", summary="missing arrays", steps=["fix"])
elif role == "planner":
    value = dict(
        status="PLAN_READY",
        summary="fix",
        steps=["Return 2, keep user comment"],
        files_read=["project/hello.py"],
        proposed_change_files=["project/hello.py"],
    )
    if mode == "new":
        value["proposed_change_files"].append("project/new.py")
    if mode == "jenkins":
        value["proposed_change_files"] = ["project/Jenkinsfile"]
        value["files_read"] = ["project/Jenkinsfile"]
    if mode == "multi":
        value["proposed_change_files"].append("jenkins/pipeline.groovy")
    if mode == "badpath":
        value["proposed_change_files"] = ["project/.git/config"]
    if mode in ("no-change", "no-change-rejected"):
        value.update(proposed_change_files=[], steps=[], summary="Current source already returns 2")
elif role == "implementer":
    if mode == "writer-timeout":
        target.write_text(target.read_text().replace("return 1", "return 2"))
        time.sleep(5)
    target.write_text(target.read_text().replace("return 1", "return 2"))
    if mode == "scope":
        (root / "unrelated.txt").write_text("corrupted")
    if mode == "new":
        (root / "new.py").write_text("VALUE = 2\n")
    if mode == "git":
        (root / ".git/HEAD").write_text("corrupted")
    if mode == "syntax" and not context.get("feedback"):
        target.write_text("def broken(\n")
    if mode == "syntax" and context.get("feedback"):
        target.write_text("# user comment\ndef hello():\n    return 2\n")
    if mode == "jenkins":
        target.write_text(target.read_text().replace("pytest -q || true", "pytest -q"))
    if mode == "multi":
        secondary = Path(context["roots"]["jenkins"]) / "pipeline.groovy"
        secondary.write_text(secondary.read_text().replace("old", "new"))
    value = dict(status="IMPLEMENTED", summary="fixed")
else:
    reject = (
        mode == "review-repair" and role == "reviewer" and "marker" not in target.read_text()
    ) or (mode == "plan-repair" and role == "plan-reviewer" and not context.get("feedback"))
    value = dict(
        status="REQUEST_CHANGES" if reject else "APPROVE",
        summary="review",
        unverified=["Runtime not run"],
        input_complete=True,
        blocking_gaps=[],
        findings=[dict(id="R1", file=str(target), criterion="marker", evidence="absent")]
        if reject
        else [],
    )
    if mode == "no-change-rejected":
        value.update(
            status="BLOCKED",
            summary="Missing required evidence",
            blocking_gaps=["Cannot confirm current behaviour"],
        )
    if mode == "incomplete-review" and role == "plan-reviewer":
        value.update(
            input_complete=False,
            blocking_gaps=["Task was truncated"],
            status="BLOCKED" if "FORMAT REPAIR ONLY" in prompt else "APPROVE",
        )
if mode == "review-repair" and role == "implementer" and context.get("feedback"):
    target.write_text(target.read_text() + "# marker\n")
if mode == "readonly-write" and role == "planner":
    target.write_text("bad")
if mode == "structured-steps" and role == "planner":
    value["steps"] = [
        dict(
            action="Update the function",
            path="project/hello.py",
            criteria="Return 2",
            checks="Static review; preserve user comment",
            dependency="none",
        )
    ]
if mode == "format-unavailable" and role == "plan-reviewer" and "FORMAT REPAIR ONLY" in prompt:
    for index in range(2):
        print(
            json.dumps(
                dict(
                    type="tool_use",
                    part=dict(
                        id="unavailable-" + str(index),
                        tool="invalid",
                        state=dict(
                            status="error",
                            input={},
                            error="Model tried to call unavailable tool 'invalid'. Available tools: .",
                        ),
                    ),
                )
            )
        )

value = enrich(value, context, target, prompt)
if mode == "two-tasks" and role == "planner" and value["proposed_change_files"]:
    first, second = value["proposed_change_files"][0], str(root / "new.py")
    value["proposed_change_files"] = [first, second]
    value["steps"] = [
        dict(value["steps"][0], id="S1", action="Return two: change hello", files=[first]),
        dict(
            value["steps"][0],
            id="S2",
            action="Add module: new file",
            files=[second],
            depends_on=["S1"],
        ),
    ]
    value["unverified"] = [
        "Jenkins check: ci/shop-tests: passes",
        "Server check: health returns 200",
    ]
if mode == "git-actions":
    for index, job in enumerate(git_jobs):
        output_path = Path(job["output_file"])
        assert header["permission"]["read"].get(str(output_path.parent) + "/*") == "allow"
        output = output_path.read_text()
        output = "\n".join(
            f"{number}: {line}" for number, line in enumerate(output.splitlines(), 1)
        )
        print(
            json.dumps(
                dict(
                    type="tool_use",
                    part=dict(
                        id=f"git-read-{index}",
                        callID=f"git-read-{index}",
                        tool="read",
                        state=dict(
                            status="completed",
                            input=dict(filePath=str(output_path)),
                            output=output,
                            metadata=dict(truncated=False),
                        ),
                    ),
                )
            )
        )
        value["evidence"].append(
            dict(
                id=f"G{index}",
                path=str(output_path),
                line_start=2,
                line_end=2,
            )
        )
if mode == "format-unavailable" and role == "plan-reviewer" and "FORMAT REPAIR ONLY" not in prompt:
    value.pop("input_complete", None)
if mode == "repair-blocked" and role == "plan-reviewer" and "PREVIOUS FINAL RESPONSE" not in prompt:
    if "FORMAT REPAIR ONLY" in prompt:
        value.update(status="BLOCKED", blocking_gaps=["The saved response omits sources"])
        value["coverage"] = [dict(entry, outcome="gap") for entry in value["coverage"]]
    else:
        value.pop("input_complete", None)
bad_citation = mode == "bad-citation" and "final result was rejected" not in prompt
bad_citation = bad_citation or (
    mode == "bad-citation-kept" and "PREVIOUS FINAL RESPONSE" not in prompt
)
if bad_citation and role == "plan-reviewer":
    value["evidence"][0].update(line_start=9, line_end=9)
if mode in {"compact", "compact-correction"} and role != "planner":
    value = dict(
        schema_version=2,
        outcomes=[
            dict(requirement=entry["id"], result=entry["outcome"], evidence=[f"{target}:1"])
            for entry in value["coverage"]
        ],
        findings=[],
        missing_inputs=[],
    )
    if mode == "compact-correction" and role == "plan-reviewer":
        if "Your final result was rejected" in prompt:
            value = dict(
                schema_version=2,
                corrections=[dict(path="/outcomes/0/result", value="planned")],
            )
        else:
            value["outcomes"][0]["result"] = "typo"
response = json.dumps(value)
plan_broken = mode in ("invalid-once", "timeout-then-invalid")
plan_broken = plan_broken and "PREVIOUS FINAL RESPONSE" not in prompt
plan_broken = plan_broken and "final result was rejected" not in prompt
if mode == "prose-block" and role == "planner":
    value.update(status="BLOCKED", blocking_gaps=["Mandatory local commands unavailable"])
plan = Path(context["task_file"]).parent.parent / "plan.md"
if role == "planner" and header["permission"]["edit"].get(str(plan)) == "allow":
    assert "PLAN FILE:" in prompt or "--session" in args
    unread = mode == "plan-unread" and "--session" not in args
    if unread:
        failure = dict(
            status="error",
            input=dict(filePath=str(plan), content="must not be written"),
            error=f"You must read the file {plan} before overwriting it.",
        )
        print(
            json.dumps(dict(type="tool_use", part=dict(id="unread", tool="write", state=failure)))
        )
    if not plan_broken and not unread:
        if mode == "plan-unread":
            assert "in THIS session" in prompt
            plan.read_text()
        plan.write_text(plan_text(value, context))
    response = "DONE"
writer_prose = mode == "writer-prose-always" or (
    mode == "writer-prose" and "FORMAT REPAIR ONLY" not in prompt
)
if writer_prose and role == "implementer":
    response = "I changed hello.py; the work is done."
if mode == "narrate" and role == "plan-reviewer" and "did not follow" not in prompt:
    response = "Let me run ansible-lint through bash -c to capture the full output."
if mode == "markup-request" and role == "planner" and "did not follow" not in prompt:
    response = '<request type="LOCAL_REQUEST"><command>python3</command><arg>print(f"{len(fixed)}")</arg></request>'
if mode == "context-overflow" and role == "planner" and "EXCEEDED THE MODEL" not in prompt:
    plan.write_text(plan.read_text().replace("Decision: single", "Decision: unfinished"))
    whole = dict(status="completed", input=dict(filePath=str(target)), output="1: x\n" * 6000)
    print(json.dumps(dict(type="tool_use", part=dict(id="whole-read", tool="read", state=whole))))
    message = "litellm.ContextWindowExceededError: Context Window exceeded for given call. Max Input Tokens=94208, Got=96808"
    overflow = dict(type="error", error=dict(name="APIError", data=dict(message=message)))
    print(json.dumps(dict(overflow, sessionID="ses1")))
    sys.exit(0)
if mode in {"planned-overflow", "unobserved-planned-overflow"} and role == "planner":
    if mode == "unobserved-planned-overflow":
        plan.write_text(
            "Decision: no change\nSummary: Assumed complete\n\n## Requirements\n"
            f"- R1 → done: {root / 'unread.py'}:1-1\n"
        )
    finish = dict(reason="tool-calls", tokens=dict(input=100000, output=2))
    print(json.dumps(dict(type="step_finish", part=finish)), flush=True)
    time.sleep(5)
    sys.exit(0)
if mode == "failed-read" and role == "planner":
    failed = dict(
        status="error", input=dict(filePath=str(root)), error=f"Error: {root} is a directory"
    )
    print(json.dumps(dict(type="tool_use", part=dict(id="failed-read", tool="read", state=failed))))
for event, part in [
    ("text", dict(text=response)),
    ("step_finish", dict(reason="stop", tokens={"input": 10, "output": 2})),
]:
    part.update(messageID="msg1", id=event)
    print(json.dumps(dict(type=event, part=part, sessionID="ses1")))
