"""Linux process runner and opencode JSONL adapter."""

import json
import os
import re
import signal
import subprocess
import time
from collections import defaultdict

from countersign.core.control import check_stop
from countersign.core.files import atomic_json
from countersign.infrastructure import opencode_cli, read_warnings, turn_io, usage_limits
from countersign.observability.progress import Progress

SUCCESS = "OK"


def stop_group(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    # Give all group members a grace period, even if the leader exits first.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def parse_events(path, start=0):
    totals = dict(input=0, output=0, reasoning=0, cache_read=0, cache_write=0, total=0)
    texts = defaultdict(list)
    sessions, tools, steps, errors, permission = set(), 0, 0, [], False
    tool_errors = []
    full_reads = []
    final_message = None
    seen = set()
    for event_line, line in turn_io.event_lines(path, start):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part", {})
        if not isinstance(part, dict):
            continue
        key = (event.get("type"), part.get("id"))
        if key[1] and key in seen:
            continue
        seen.add(key)
        if event.get("sessionID"):
            sessions.add(event["sessionID"])
        kind = event.get("type")
        if kind == "text" and isinstance(part.get("text"), str):
            texts[part.get("messageID")].append(part["text"])
        if kind == "tool_use":
            tools += 1
            tool_state = part.get("state", {})
            if tool_state.get("status") == "error":
                error = str(tool_state.get("error", "unknown tool error"))
                errors.append(error)
                permission |= opencode_cli.permission_error(error)
                tool_errors.append(
                    dict(
                        tool=part.get("tool"),
                        call_id=part.get("callID"),
                        input=tool_state.get("input", {}),
                        error=error,
                        event_line=event_line,
                    )
                )
            elif part.get("tool") == "read" and tool_state.get("status") == "completed":
                data = tool_state.get("input", {})
                output = tool_state.get("output", "")
                metadata = tool_state.get("metadata") or {}
                if (
                    isinstance(output, str)
                    and data.get("offset", 1) == 1
                    and not metadata.get("truncated")
                ):
                    end = re.search(r"\(End of file - total (\d+) lines\)", output)
                    body = output.split("<content>", 1)[-1].split("</content>", 1)[0]
                    numbers = [int(n) for n in re.findall(r"^\s*(\d+):", body, re.M)]
                    if (
                        end
                        and len(numbers) == int(end.group(1))
                        and all(n == i for i, n in enumerate(numbers, 1))
                    ):
                        full_reads.append(
                            (event_line, data.get("filePath"), part.get("callID"), part.get("id"))
                        )
        if kind == "error":
            error = str(event.get("error", event))
            errors.append(error)
            permission |= opencode_cli.permission_error(error)
        if kind == "step_finish":
            steps += 1
            tokens = part.get("tokens", {})
            for field in ("input", "output", "reasoning", "total"):
                val = tokens.get(field, 0)
                totals[field] += val if isinstance(val, (int, float)) else 0
            for field in ("read", "write"):
                val = tokens.get("cache", {}).get(field, 0)
                totals["cache_" + field] += val if isinstance(val, (int, float)) else 0
            if part.get("reason") == "stop":
                final_message = part.get("messageID")
    warnings = []
    for item in tool_errors:
        if item["tool"] != "read" or not re.fullmatch(
            r"Error: Offset \d+ is out of range for this file \(\d+ lines\)", item["error"]
        ):
            continue
        source = item["input"].get("filePath")
        if not isinstance(source, str) or not os.path.isabs(source):
            continue
        corrected = next(
            (read for read in full_reads if read[0] > item["event_line"] and read[1] == source),
            None,
        )
        if corrected:
            item["recovered_by"] = dict(
                event_line=corrected[0], call_id=corrected[2], part_id=corrected[3]
            )
            warnings.append(dict(item))
            errors.remove(item["error"])
    return read_warnings.classify_missing_reads(
        {
            "tokens": totals,
            "steps": steps,
            "tool_calls": tools,
            "warnings": warnings,
            "sessions": sorted(sessions),
            "errors": errors,
            "tool_errors": tool_errors,
            "permission": permission,
            "completed": final_message is not None,
            "final_text": "\n".join(texts.get(final_message, [])) if final_message else "",
        }
    )


def permission_denied_event(line):
    try:
        event = json.loads(line)
    except ValueError:
        return False
    if not isinstance(event, dict):
        return False
    error = ""
    if event.get("type") == "tool_use":
        part = event.get("part", {})
        state = part.get("state", {}) if isinstance(part, dict) else {}
        if isinstance(state, dict) and state.get("status") == "error":
            error = str(state.get("error", ""))
    elif event.get("type") == "error":
        error = str(event.get("error", ""))
    return opencode_cli.permission_error(error)


def run_agent(
    command,
    workspace,
    agent,
    model,
    prompt,
    attempt,
    timeout,
    debug=False,
    progress=False,
    format_only=False,
    runtime=None,
):
    attempt.mkdir(exist_ok=True)
    turn = turn_io.TurnIO(attempt, runtime)
    turn.prepare(prompt)
    argv, env = turn.launch(command, model)
    if debug:
        argv += ["--print-logs", "--log-level", "DEBUG"]
    argv += [
        "--dir",
        str(workspace),
        "--agent",
        agent,
        "--format",
        "json",
        "--file",
        str(prompt),
        "--",
        "Execute_the_task_in_the_attached_file",
    ]
    started = time.monotonic()
    status, rc = SUCCESS, None
    activity = Progress(attempt / "activity.json")
    telemetry = turn.telemetry()
    offset, pending = len(turn.previous), b""
    with turn.open() as out, turn.error_stream() as err:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            err.write(str(exc).encode())
            status = "LAUNCH_ERROR"
        else:
            try:
                deadline = time.monotonic() + timeout
                next_progress = started + 30
                while True:
                    check_stop(attempt.parent)
                    with (attempt / "events.jsonl").open("rb") as stream:
                        stream.seek(offset)
                        chunk = stream.read()
                        offset = stream.tell()
                    lines = (pending + chunk).split(b"\n")
                    pending = lines.pop()
                    if lines:
                        activity.observe(lines)
                        for line in lines:
                            telemetry.observe(line)
                        atomic_json(attempt / "telemetry.json", telemetry.value())
                    status = usage_limits.exceeded(telemetry, turn.token_budget)
                    if status != SUCCESS:
                        stop_group(proc.pid)
                        rc = proc.wait()
                        break
                    if any(permission_denied_event(line) for line in lines):
                        status = "BLOCKED_PERMISSION"
                        stop_group(proc.pid)
                        rc = proc.wait()
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(argv, timeout)
                    try:
                        rc = proc.wait(timeout=min(0.2, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            raise
                        if progress and time.monotonic() >= next_progress:
                            print(
                                activity.line(
                                    time.monotonic() - started,
                                    (attempt / "events.jsonl").stat().st_size,
                                ),
                                flush=True,
                            )
                            next_progress = time.monotonic() + 30
            except subprocess.TimeoutExpired:
                status = "TIMEOUT"
                stop_group(proc.pid)
                rc = proc.wait()
            except BaseException:
                stop_group(proc.pid)
                proc.wait()
                raise
            finally:
                # Also clean up children left in the process group on normal exit.
                stop_group(proc.pid)
    with (attempt / "events.jsonl").open("rb") as stream:
        stream.seek(offset)
        final_lines = (pending + stream.read()).splitlines()
        activity.observe(final_lines)
        for line in final_lines:
            telemetry.observe(line)
    atomic_json(attempt / "telemetry.json", telemetry.value())
    if status == SUCCESS:
        status = usage_limits.exceeded(telemetry, turn.token_budget)
    result = parse_events(turn.path, len(turn.previous.splitlines()))
    stderr = turn.error_text()
    if format_only and status == SUCCESS and rc == 0 and "auto-rejecting" not in stderr:
        recover_unavailable_format_tools(result)
    if status == SUCCESS:
        if result["permission"] or "auto-rejecting" in stderr:
            status = "BLOCKED_PERMISSION"
        elif rc != 0:
            status = "PROCESS_ERROR"
        elif result["errors"]:
            status = "TOOL_ERROR"
        elif not result["completed"] or not result["final_text"].strip():
            status = "INCOMPLETE"
    result.update(
        status=status,
        exit_code=rc,
        elapsed_seconds=round(time.monotonic() - started, 3),
        model=model,
        agent=agent,
        usage_complete=status == SUCCESS,
    )
    (attempt / "response.raw.txt").write_text(result["final_text"], encoding="utf-8")
    return result


def recover_unavailable_format_tools(result):
    """Retain rejected calls as warnings only for a completed, tool-free format pass.

    The caller still validates the final JSON and source integrity. Any permission
    denial, available tool, successful call or other transport error stays fatal.
    """
    errors = result.get("tool_errors", [])
    pattern = r"Model tried to call unavailable tool '[^']+'. Available tools:\s*\.?"
    if (
        not result.get("completed")
        or not result.get("final_text", "").strip()
        or result.get("permission")
        or not errors
        or result.get("tool_calls") != len(errors)
        or result.get("errors") != [item["error"] for item in errors]
        or any(not re.fullmatch(pattern, item["error"]) for item in errors)
    ):
        return
    for item in errors:
        item["resolution"] = (
            "Rejected unavailable tool in a tool-free format pass; nothing executed. Final JSON still requires validation."
        )
        result["warnings"].append(dict(item))
    result["errors"] = []
