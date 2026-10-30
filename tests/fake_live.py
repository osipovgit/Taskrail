"""Subprocess fixture: CLI, installed profiles and JSON events, not a real model."""

import builtins
import json
import os
import sys
import time
import uuid
from pathlib import Path

from fake_contract import attempt, earlier_invalid, enrich, plan_text, review_text
from fake_file_writes import event as file_event
from fake_file_writes import implement
from fake_report_repair import report_result

args = sys.argv[1:]
if "--version" in args:
    print("1.0.0")
    sys.exit(0)
if args[-2:] == ["run", "--help"]:
    print("run --session --dir --agent --format --file")
    sys.exit(0)
profiles = Path(args[args.index("--profiles") + 1])
mode = args[args.index("--mode") + 1]
if "agent" in args:
    for path in sorted(profiles.glob("taskrail-*.md")):
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
request_file = Path(args[args.index("--file") + 1])
prompt = request_file.read_text()
# The attempt record decides the behavior: its stage, its mode and the earlier attempts.
record = attempt(args)
role = record["stage"]
run = request_file.parent.parent
# Every turn attaches the stage's own run file after the prompt, and only that file.
attached = [args[index + 1] for index, item in enumerate(args) if item == "--file"][1:]
owned = dict(planner="plan.md", implementer="progress.md", reviewer="review.md")
owned["plan-reviewer"] = "review.md"
own = run / owned[role] if role in owned else None
assert attached == ([] if own is None else [str(own)]), attached
continued = "--session" in args
rebuilt = earlier_invalid(run, record)
saved_context = profiles / "fixture-context.json"
request = (request_file.parent / "request.md").read_text()
if "Context:\n" in request:
    context, _ = json.JSONDecoder().raw_decode(request.split("Context:\n", 1)[1])
    saved_context.write_text(json.dumps(context))
else:
    context = json.loads(saved_context.read_text())
# Requirement IDs and kinds are server state; the request labels them R1, R2, ...
context["requirements"] = [
    dict(id=entry["id"], kind=entry["kind"])
    for entry in json.loads((run / "run.json").read_text())["requirements"]
]
header = json.loads((profiles / (agent + ".md")).read_text().split("---")[1])
for file in [request_file, Path(context["task_file"])] + (
    [Path(context["diff_file"])] if context.get("diff_file") else []
):
    assert header["permission"]["read"].get(str(file)) == "allow", str(file)
    assert header["permission"]["external_directory"].get(str(file.parent) + "/*") == "allow", str(
        file.parent
    )
if mode == "scenario":
    from acceptance.fixture_agent import execute

    execute(context, role, args, print)
    sys.exit(0)
root = Path(context["roots"]["project"])
target = root / ("Jenkinsfile" if mode == "jenkins" else "hello.py")
if mode == "report-repair":
    report_result(context, prompt, header, print)
    sys.exit(0)
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
if mode in {"bad-git-request", "local-effects"} and role == "planner" and "--session" not in args:
    if mode == "bad-git-request":
        request = dict(schema_version=1, status="GIT_REQUEST", root=str(root), argv=["log", "-1"])
        request.update(reason="History", cwd=str(root))
    else:
        script = "open('.cache-tool/report.txt','w').write('x'); open('notes.txt','w').write('y')"
        script = "import os; os.makedirs('.cache-tool', exist_ok=True); " + script
        request = dict(schema_version=1, status="LOCAL_REQUEST", cwd=str(root))
        request.update(argv=[sys.executable, "-c", script], reason="Run the tool")
    for event, part in [
        ("text", dict(text="```json\n" + json.dumps(request) + "\n```")),
        ("step_finish", dict(reason="stop", tokens={"input": 10, "output": 2})),
    ]:
        part.update(messageID="msg1", id=event)
        print(json.dumps(dict(type=event, part=part, sessionID="ses1")))
    sys.exit(0)
if mode == "ssh-action" and role == "planner" and not (run / "execution.json").exists():
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
if (
    mode in ("review-denied-once", "review-denied-always")
    and role == "reviewer"
    and (mode == "review-denied-always" or "--session" not in args)
):
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
if (
    mode in ("parent-once", "parent-twice")
    and role == "plan-reviewer"
    and (mode == "parent-twice" or "--session" not in args)
):
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
    numbered = "\n".join(f"{i}:{line}" for i, line in enumerate(target.read_text().splitlines(), 1))
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
if role == "implementer":
    assert all(Path(name).is_absolute() for name in context["allowed_files"])
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
    evidence = request_file.parent / "recovery.md"
    assert "return 1" in evidence.read_text()
    assert record["mode"] == "research-recovery", record["mode"]
    assert record["inputs"]["recovery"] == str(evidence.relative_to(run))
    assert header["permission"]["read"][str(evidence)] == "allow"
    assert header["permission"]["external_directory"][str(evidence.parent) + "/*"] == "allow"
if role == "planner":
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
    if mode in ("no-change", "no-change-rejected", "wrapped-no-change"):
        value.update(proposed_change_files=[], steps=[], summary="Current source already returns 2")
elif role == "implementer":
    if mode == "writer-timeout":
        target.write_text(target.read_text().replace("return 1", "return 2"))
        time.sleep(5)
    if mode.startswith("write-"):
        implement(target, mode, print)
    else:
        target.write_text(target.read_text().replace("return 1", "return 2"))
    if mode == "scope":
        (root / "unrelated.txt").write_text("corrupted")
    if mode == "new":
        (root / "new.py").write_text("VALUE = 2\n")
    if mode == "git":
        (root / ".git/HEAD").write_text("corrupted")
    if mode == "secret-added":
        kept = [line for line in target.read_text().splitlines(True) if "TOKEN" not in line]
        if not context.get("feedback"):
            kept.append('TOKEN = "' + "ghp_" + "x" * 36 + '"\n')
        target.write_text("".join(kept))
    if mode == "syntax-stuck":
        target.write_text("def broken(\n")
    if mode == "progress-unread":
        progress = run / "progress.md"
        rejection = f"You must read file {progress} before overwriting it. Use the Read tool first"
        file_event(print, progress, "write", "error", rejection)
    if mode == "syntax" and not context.get("feedback"):
        target.write_text("def broken(\n")
    if mode == "syntax" and context.get("feedback"):
        target.write_text("# user comment\ndef hello():\n    return 2\n")
    if mode == "jenkins":
        target.write_text(target.read_text().replace("pytest -q || true", "pytest -q"))
    if mode == "multi":
        secondary = Path(context["roots"]["jenkins"]) / "pipeline.groovy"
        secondary.write_text(secondary.read_text().replace("old", "new"))
    if mode == "integration-fix":
        target.write_text(target.read_text() + "# marker\n")
    value = dict(status="IMPLEMENTED", summary="fixed")
else:
    reject = (
        mode == "review-repair" and role == "reviewer" and "marker" not in target.read_text()
    ) or (mode == "plan-repair" and role == "plan-reviewer" and not context.get("feedback"))
    reject = reject or (mode == "integration-reject" and role == "reviewer")
    value = dict(
        status="REQUEST_CHANGES" if reject else "APPROVE",
        summary="review",
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
        value.update(status="BLOCKED", blocking_gaps=["Task was truncated"])
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
if mode == "review-preimage" and role == "reviewer":
    target = run / "00-input/preimages/project/hello.py"
value = enrich(value, context, target, role, read_wrapper=mode == "wrapped-no-change")
if mode == "integration-fix" and role == "planner":
    value["steps"][0]["required_checks"] = ["audit"]
if mode == "wrapped-no-change":
    value["evidence"][0]["line_end"] = len(target.read_text().splitlines())
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
    if any(recipe["id"] == "health" for recipe in context.get("check_catalog", [])):
        value["steps"][0]["required_checks"] = ["health"]
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
bad_citation = mode == "bad-citation" and not continued
bad_citation = bad_citation or (mode == "bad-citation-kept" and not rebuilt)
if bad_citation and role == "plan-reviewer":
    value["evidence"][0].update(line_start=9, line_end=9)
response = json.dumps(value)
if role == "implementer":
    gaps = value["blocking_gaps"] if value["status"] == "BLOCKED" else []
    response = "BLOCKED: " + "; ".join(gaps) if gaps else "DONE: " + value.get("summary", "done")
if role in ("plan-reviewer", "reviewer"):
    (run / "review.md").write_text(review_text(value, context))
    response = "DONE"
plan_broken = mode in ("invalid-once", "timeout-then-invalid") and not (continued or rebuilt)
if mode == "prose-block" and role == "planner":
    value.update(status="BLOCKED", blocking_gaps=["Mandatory local commands unavailable"])
plan = run / "plan.md"
if role == "planner" and header["permission"]["edit"].get(str(plan)) == "allow":
    assert "PLAN FILE:" in prompt or continued
    unread = mode in {"plan-unread", "plan-unread-resolved"} and not continued
    if unread:
        failure = dict(
            status="error",
            input=dict(filePath=str(plan), content="must not be written"),
            error=f"You must read file {plan} before overwriting it. Use the Read tool first",
        )
        print(
            json.dumps(dict(type="tool_use", part=dict(id="unread", tool="write", state=failure)))
        )
    if mode == "plan-unread-resolved":
        for tool, output in (("read", plan.read_text()), ("write", "File written successfully")):
            state = dict(status="completed", input=dict(filePath=str(plan)), output=output)
            part = dict(id="plan-" + tool, callID="plan-" + tool, tool=tool, state=state)
            print(json.dumps(dict(type="tool_use", part=part)))
        unread = False
    if not plan_broken and not unread:
        if mode == "plan-unread":
            assert "in THIS session" in prompt
            plan.read_text()
        plan.write_text(plan_text(value, context))
    response = "DONE"
writer_prose = mode in {"writer-prose-always", "writer-extra-prose-always"} or (
    mode == "writer-prose" and not continued
)
if mode == "writer-extra-prose-always" and role == "implementer":
    (root / "extra.txt").write_text("Required companion change\n")
if writer_prose and role == "implementer":
    response = "I changed hello.py; the work is done."
if mode == "narrate" and role == "plan-reviewer" and not continued:
    response = "Let me run ansible-lint through bash -c to capture the full output."
if mode == "markup-request" and role == "planner" and not continued:
    response = '<request type="LOCAL_REQUEST"><command>python3</command><arg>print(f"{len(fixed)}")</arg></request>'
if mode == "context-overflow" and role == "planner" and record["mode"] == "model":
    plan.write_text(plan.read_text().replace("Decision: single", "Decision: unfinished"))
    whole = dict(status="completed", input=dict(filePath=str(target)), output="1: x\n" * 6000)
    print(json.dumps(dict(type="tool_use", part=dict(id="whole-read", tool="read", state=whole))))
    message = "litellm.ContextWindowExceededError: Context Window exceeded for given call. Max Input Tokens=94208, Got=96808"
    overflow = dict(type="error", error=dict(name="APIError", data=dict(message=message)))
    print(json.dumps(dict(overflow, sessionID="ses1")))
    sys.exit(0)
if mode == "large-progress-context" and role == "implementer" and record["mode"] == "model":
    (run / "progress.md").write_text("# Done\n" + "x" * 1900000 + "\n# Remaining\nFinish review\n")
    overflow = dict(name="APIError", data=dict(message="context_length_exceeded"))
    print(json.dumps(dict(type="error", error=overflow, sessionID="ses1")))
    sys.exit(0)
if mode == "provider-interrupted" and role == "implementer" and not continued:
    target.write_text(target.read_text().replace("return 1", "return 2"))
    gateway = dict(name="APIError", data=dict(message="Retries exhausted", isRetryable=False))
    print(json.dumps(dict(type="error", error=gateway, sessionID="ses1")))
    sys.exit(0)
if mode == "provider-quota" and role == "plan-reviewer":
    quota = dict(type="provider.quota", message="Free usage limit reached.", status=429)
    print(json.dumps(dict(type="error", error=quota, sessionID="ses1")))
    sys.exit(1)
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
if mode.startswith("invalid-tool-") and role == "reviewer":
    if not continued or mode == "invalid-tool-bad-review":
        rejected = dict(status="error", input={}, error="Model tried unavailable tool 'invalid'")
        print(
            json.dumps(
                dict(type="tool_use", part=dict(id="invalid", tool="invalid", state=rejected))
            )
        )
    if mode == "invalid-tool-incomplete" and not continued:
        response = "The review is almost ready."
    elif mode == "invalid-tool-bad-review":
        (run / "review.md").write_text("Summary: Done\n")
    else:
        response = "Every requirement was checked against current source.\nDONE"
for event, part in [
    ("text", dict(text=response)),
    ("step_finish", dict(reason="stop", tokens={"input": 10, "output": 2})),
]:
    part.update(messageID="msg1", id=event)
    print(json.dumps(dict(type=event, part=part, sessionID="ses1")))
