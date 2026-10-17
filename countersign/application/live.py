"""Live source workflow with controlled Git and no automatic rollback."""

import ast
import difflib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from countersign.application import (
    access_recovery,
    attempt_context,
    evidence,
    instruction_sources,
    prompts,
    result_context,
    resume_inputs,
    transitions,
)
from countersign.application.artifacts import finish_stage, new_stage, save_run
from countersign.application.checkpoints import RESUMABLE, budget_paused, load_checkpoint
from countersign.application.recovery import write_evidence
from countersign.core import control, requirements
from countersign.core.files import atomic_json, changed
from countersign.core.paths import readable_source, tool_paths
from countersign.core.runtime import (
    DEFAULT_TIMEOUT,
    SOFTWARE_VERSION,
    run_storage,
    settings_path,
)
from countersign.infrastructure import artifact_access, opencode_api
from countersign.infrastructure.agent_sync import (
    atomic_write,
    launch_settings,
    make_profile,
    repair_mode,
    verify_permissions,
)
from countersign.interactions.session import run_stage
from countersign.observability.progress import clock
from countersign.observability.telemetry import inspect_events

STAGE = "stage"
RUNNING = "RUNNING"
PREIMAGES = "preimages"

FILE_PERMISSION_MASK = 0o777

FORBIDDEN = {".git", ".hg", ".svn", ".opencode", ".ssh", ".kube"}
SKIP = frozenset(
    (
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".cache",
    )
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def configuration(task, settings=None, roots_override=None):
    task = Path(task).expanduser().resolve(strict=True)
    text = task.read_text(encoding="utf-8")
    headers = re.findall(r"(?ms)^```countersign-task\s*\n(.*?)^```\s*$", text)
    if len(headers) > 1:
        raise ValueError("Only one countersign-task header is supported")
    meta = json.loads(headers[0]) if headers else {}
    settings = settings_path(settings)
    options = json.loads(settings.read_text()) if settings.exists() else {}
    if not isinstance(meta, dict) or not isinstance(options, dict):
        raise ValueError("Task header and settings must be JSON objects")
    if roots_override is not None:
        meta["roots"] = roots_override
    if "roots" not in meta:
        root = next((p for p in task.parents if (p / ".git").exists()), None)
        if root is None:
            raise ValueError("Task outside a repository needs countersign-task JSON with roots")
        meta["roots"] = {"project": str(root)}
    roots = {}
    if not isinstance(meta["roots"], dict):
        raise ValueError("roots must be an alias-to-path object")
    for alias, raw in meta["roots"].items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", alias) or not isinstance(raw, str):
            raise ValueError("Invalid root alias/path")
        candidate = Path(raw).expanduser()
        root = (
            (task.parent / candidate).resolve(strict=True)
            if not candidate.is_absolute()
            else candidate.resolve(strict=True)
        )
        if not root.is_dir() or root == Path(root.anchor):
            raise ValueError("Project must be an existing non-filesystem-root directory")
        if any(c in str(root) for c in "*?\n\r"):
            raise ValueError("Wildcard/newline in root is not supported")
        for existing in roots.values():
            if root == existing or root in existing.parents or existing in root.parents:
                raise ValueError("Project roots must not overlap")
        roots[alias] = root
    if not roots:
        raise ValueError("At least one project root required")
    source = Path(
        options.get("agent_source", str(Path(__file__).resolve().parents[2] / "agents"))
    ).expanduser()
    if not source.is_absolute():
        source = settings.parent / source
    agents = {role: role for role in ("planner", "implementer", "reviewer")}
    for role in ("planner", "implementer", "reviewer"):
        if not (source / (agents[role] + ".md")).is_file():
            raise ValueError("Missing source agent: " + agents[role])
        instruction_sources.validate_role_source(source / f"{agents[role]}.md")
    verification = meta.get("verification", [])
    worktree = options.get("permission_worktree")
    if worktree is not None:
        worktree = Path(worktree).expanduser()
        if not worktree.is_absolute() or not worktree.is_dir():
            raise ValueError(
                "permission_worktree must be an existing absolute directory from opencode logs"
            )
        worktree = worktree.resolve()
    if not isinstance(verification, list) or any(not isinstance(x, str) for x in verification):
        raise ValueError("verification must list runtime acceptance checks as strings")
    return dict(
        launch_settings(options, settings.parent),
        stage_seconds=max(1, int(options.get("stage_timeout_seconds", DEFAULT_TIMEOUT * 4))),
        stage_attempts=max(1, int(options.get("max_stage_attempts", 6))),
        read_only=meta.get("read_only") is True,
        task=task,
        task_text=text,
        roots=roots,
        source=source.resolve(),
        max_observed_tokens=max(0, int(options.get("max_observed_tokens", 0))),
        agents=agents,
        verification=verification,
        permission_worktree=worktree,
        timeout=max(1, int(options.get("timeout_seconds", DEFAULT_TIMEOUT))),
        max_repairs=max(0, min(5, int(options.get("max_repairs", 3)))),
        read_retries=max(0, min(3, int(options.get("read_retries", 3)))),
        run_base=run_storage(settings),
    )


def safe_file(name, roots):
    if not isinstance(name, str) or not name or any(c in name for c in "*?\r\n"):
        raise ValueError("Invalid planned file")
    parts = Path(name).parts
    if len(parts) < 2 or parts[0] not in roots or str(Path(name)) != name or ".." in parts:
        raise ValueError("Use normalized alias/relative/file: " + name)
    if any(part in (FORBIDDEN | SKIP) or part.startswith(".env") for part in parts[1:]):
        raise ValueError("Protected path in plan: " + name)
    path = roots[parts[0]]
    for part in parts[1:]:
        path /= part
        if path.is_symlink():
            raise ValueError("Symlink in planned path: " + name)
    if path.exists() and not path.is_file():
        raise ValueError("Planned path is not a regular file: " + name)
    if path.exists() and path.stat().st_nlink != 1:
        raise ValueError("Hard-linked files cannot be edited: " + name)
    return path


def validate_plan(plan, roots, task, config=None):
    if plan["status"] != "PLAN_READY":
        return
    control.check_plan(plan, config or {})
    proposed, read = plan.get("proposed_change_files"), plan.get("files_read")
    if (
        not isinstance(proposed, list)
        or any(not isinstance(n, str) for n in proposed)
        or len(proposed) != len(set(proposed))
    ):
        raise ValueError("Plan needs unique proposed_change_files")
    control.check_reads(read, plan.get("evidence"))
    for name in proposed:
        safe_file(name, roots)
    for name in read:
        readable_source(name, roots)
    if task in [safe_file(n, roots) for n in proposed]:
        raise ValueError("Task specification must not be edited")


def snapshot(roots, cache=None):
    """Hash source bytes, not copy trees. No traversal through symlinks."""
    result = {}
    cache = {} if cache is None else cache
    for alias, root in roots.items():
        for directory, dirs, files in os.walk(str(root), followlinks=False):
            base = Path(directory)
            for entry in list(dirs):
                path = base / entry
                if path.is_symlink():
                    result[alias + "/" + path.relative_to(root).as_posix()] = "link:" + os.readlink(
                        path
                    )
                    dirs.remove(entry)
                elif entry in SKIP:
                    dirs.remove(entry)
            for entry in files:
                path = base / entry
                name = alias + "/" + path.relative_to(root).as_posix()
                if path.is_symlink():
                    result[name] = "link:" + os.readlink(path)
                elif path.is_file():
                    result[name] = cached_fingerprint(path, cache)
                else:
                    raise ValueError("Unsupported special file: " + str(path))
    return result


def source_stamp(path):
    """Track bytes, permissions and identity when reusing an integrity hash."""
    metadata = path.stat()
    return [
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_mode,
        metadata.st_nlink,
    ]


def stream_digest(path):
    """Hash large source files without reading the complete file into memory."""
    digestor = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digestor.update(chunk)
    return digestor.hexdigest()


def cached_fingerprint(path, cache):
    """Reuse a content hash only while all source identity fields are unchanged."""
    stamp = source_stamp(path)
    previous = cache.get(str(path))
    if previous and previous[0] == stamp:
        return previous[1]
    signature = "%o:%s" % (stamp[5] & FILE_PERMISSION_MASK, stream_digest(path))
    cache[str(path)] = (stamp, signature)
    return signature


def git_metadata(roots):
    """Small Git control_root files only; never read/copy Git objects or invoke Git."""
    result = {}
    for alias, root in roots.items():
        git = result_context.git_reference(root)
        if git.is_file():
            raw = git.read_text().strip()
            result[alias + "/.git"] = digest(git.read_bytes())
            if raw.startswith("gitdir: "):
                git = (git.parent / raw[8:]).resolve()
        if not git.is_dir():
            continue
        dirs = [git]
        if (git / "commondir").is_file():
            dirs.append((git / (git / "commondir").read_text().strip()).resolve())
        for index, control_root in enumerate(dirs):
            candidates = [
                control_root / n
                for n in ("HEAD", "index", "config", "packed-refs", "ORIG_HEAD", "commondir")
            ]
            if (control_root / "refs").exists():
                candidates += list((control_root / "refs").rglob("*"))
            for p in candidates:
                if p.is_file():
                    result[f"{alias}/{index}/{p.relative_to(control_root)}"] = digest(
                        p.read_bytes()
                    )
    return result


def syntax_checks(roots, names, run):
    checks = []
    for name in names:
        path = safe_file(name, roots)
        if not path.exists():
            checks.append(dict(file=name, status="SKIPPED", detail="deleted file"))
            continue
        kind = path.suffix
        try:
            if kind == ".py":
                import tokenize

                with tokenize.open(str(path)) as stream:
                    ast.parse(stream.read(), filename=str(path))
                detail = "Python syntax (no execution)"
            elif kind == ".json":
                json.loads(path.read_text())
                detail = "JSON syntax"
            elif kind == ".sh":
                # Trusted fixed argv, no model-generated commands; bash -n executes nothing.
                done = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-n", str(path)],
                    env={"PATH": os.defpath},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                if done.returncode:
                    raise ValueError(done.stderr.decode(errors="replace"))
                detail = "bash -n (no execution)"
            else:
                checks.append(
                    dict(file=name, status="SKIPPED", detail="No built-in syntax validator")
                )
                continue
            checks.append(dict(file=name, status="PASS", detail=detail))
        except (ValueError, SyntaxError, OSError, subprocess.TimeoutExpired) as exc:
            checks.append(dict(file=name, status="FAIL", detail=str(exc)))
    atomic_json(run / "result.json", checks)
    return checks


def write_diff(run, roots, preimages):
    output = []
    for name, original in preimages.items():
        path = safe_file(name, roots)
        before = (run / original).read_bytes() if original else b""
        after = path.read_bytes() if path.exists() else b""
        if before == after:
            continue
        if b"\0" in before or b"\0" in after:
            output.append("Binary file changed: " + str(path) + "\n")
        else:
            lines = difflib.unified_diff(
                before.decode("utf-8", "replace").splitlines(True),
                after.decode("utf-8", "replace").splitlines(True),
                fromfile=str(path) if original else "/dev/null",
                tofile=str(path) if path.exists() else "/dev/null",
            )
            for line in lines:
                output.append(
                    line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                )
    (run / "changes.diff").write_text("".join(output), encoding="utf-8")


def canonical_plan(value, roots):
    """Accept in-root absolute paths in planner arrays; store alias paths internally."""
    for field in ("files_read", "proposed_change_files"):
        entries = value.get(field)
        if not isinstance(entries, list):
            continue
        converted = []
        for name in entries:
            if isinstance(name, str) and Path(name).is_absolute():
                for alias, root in roots.items():
                    try:
                        name = alias + "/" + Path(name).relative_to(root).as_posix()
                        break
                    except ValueError:
                        pass
            converted.append(name)
        value[field] = converted
    return value


def report(run, state):
    lines = [
        "# Countersign — review report",
        "",
        "Status: " + state["status"],
        "",
        state.get("summary", ""),
        "",
        "Source files are edited in place. Git uses the controlled executor; no automatic rollback.",
        "",
        "## Timeline",
        "",
        "| # | Stage | Role | Mode | Status |",
        "|---|---|---|---|---|",
    ]
    for item in state["stages"]:
        directory = item["directory"]
        lines.append(
            "| %s | [%s](%s/stage.json) | %s | %s | %s |"
            % (
                item["number"],
                directory,
                directory,
                item.get("role") or "system",
                item["mode"],
                item["status"] + (" / " + item["verdict"] if item.get("verdict") else ""),
            )
        )
    lines += ["", "## Changed files", ""]
    lines += ["- " + name for name in state.get("changed_files", [])] or ["No recorded changes."]
    lines += ["", "## Source projects", ""]
    lines += ["- " + alias + ": " + path for alias, path in state["roots"].items()]
    lines += ["", "## Checks", ""]
    lines += ["- {file}: {status} — {detail}".format(**item) for item in state["checks"]] or [
        "Built-in checks were skipped: no changes are required."
        if state["status"] == "NO_CHANGES_REQUIRED"
        else "Checks have not run yet."
    ]
    for item in state["stages"]:
        if item.get("errors") or item.get("tool_errors"):
            lines += ["", "## Stage errors: " + item["directory"], ""]
            for error in item.get("tool_errors", []):
                lines += [
                    "- Tool: " + str(error.get("tool")),
                    "  Input: `" + json.dumps(error.get("input"), ensure_ascii=False) + "`",
                    "  Error: " + error["error"],
                ]
                if error.get("resolution"):
                    lines += ["  Resolution: " + error["resolution"]]
                if error.get("recovered_by"):
                    lines += [
                        "  Recovered by a later full read; event: "
                        + str(error["recovered_by"]["event_line"])
                    ]
            if not item.get("tool_errors"):
                lines += ["- " + error for error in item.get("errors", [])]
    lines += result_context.execution_report(state)
    lines += [
        "",
        "## Not verified",
        "",
        "- Only explicitly recorded checks/actions were executed; other runtime criteria remain unverified.",
    ]
    lines += ["- " + item for item in dict.fromkeys(state["unverified"])]
    for item in state.get("review_limits", []):
        lines += ["", f"### Review limitations: {item[STAGE]}", ""]
        lines += ["- " + text for text in item["unverified"]]
        lines += ["- Blocking gap: " + text for text in item["blocking_gaps"]]
    lines += ["", "## Results", "", "- [Run index](run.json)"]
    for key, ref in state["results"].items():
        if (run / ref).is_file():
            lines.append("- [%s](%s)" % (key, ref))
    if (run / "changes.diff").exists():
        lines.append("- [Changes](changes.diff)")
    lines += [
        "",
        "For diagnostics, provide run.json and the affected stage directory.",
        "On failure, partial changes are preserved; there is no automatic rollback.",
        "",
    ]
    (run / "report.md").write_text(tool_paths("\n".join(lines), state["roots"]), encoding="utf-8")
    save_run(run, state)


def execute_task(task, settings=None, debug=False, run_dir=None, plan_response=None, resume=False):
    restored_roots = (
        json.loads((Path(run_dir).expanduser().resolve() / "run.json").read_text())["roots"]
        if resume
        else None
    )
    config = configuration(task, settings, roots_override=restored_roots)
    task_text = config["task_text"]
    seed = Path(plan_response).expanduser().read_text(encoding="utf-8") if plan_response else None
    roots = config["roots"]
    run = (
        Path(run_dir).expanduser().resolve()
        if run_dir
        else config["run_base"] / (time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(4).hex())
    )
    if any(run == root or root in run.parents for root in roots.values()):
        raise ValueError("Run logs must be outside source roots")
    inputs = run / "00-input"
    if resume:
        if plan_response:
            raise ValueError("Cannot combine resume with plan import")
        state = json.loads((run / "run.json").read_text())
        if state["status"] not in RESUMABLE and not budget_paused(state):
            raise ValueError("This run is not interrupted; use Restart instead")
        if state["roots"] != {key: str(path) for key, path in roots.items()}:
            raise ValueError("Project roots changed; cannot continue")
    else:
        run.mkdir(parents=True, exist_ok=False)
        inputs = run / "00-input"
        inputs.mkdir()
        atomic_write(inputs / "task.md", task_text.encode())
        if seed is not None:
            atomic_write(inputs / "imported-response.raw.txt", seed.encode())
        state = dict(
            version=4,
            software_version=SOFTWARE_VERSION,
            contract_version=1,
            requirements=requirements.task_requirements(task_text, config["verification"]),
            status=RUNNING,
            stage="preflight",
            roots={key: str(path) for key, path in roots.items()},
            task=str(config["task"]),
            started_at=clock(),
            monitoring=dict(
                max_observed_tokens=config["max_observed_tokens"],
            ),
            stages=[],
            attempts=[],
            changed_files=[],
            checks=[],
            unverified=config["verification"],
            preimages={},
            results={},
        )
        atomic_json(
            inputs / "settings.json",
            {
                key: config[key]
                for key in (
                    "opencode_version",
                    "models",
                    "timeout",
                    "stage_seconds",
                    "stage_attempts",
                    "read_retries",
                    "max_repairs",
                    "max_observed_tokens",
                )
            },
        )
        save_run(run, state)
        print("Run: " + str(run), flush=True)
    before, git_before, active = None, None, None
    profiles, allowed, scan_cache = [], [], {}
    stage, expected, plan, feedback = "planner", {}, None, None
    plan_repairs = repair_count = 0

    def scan():
        return snapshot(roots, scan_cache)

    lock_path = Path.home() / ".local/state/countersign/live.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if resume:
                raise ValueError("Another live run holds the lock; continuation was not started")
            state.update(status="BLOCKED", summary="Another live run holds the lock")
            report(run, state)
            return run, state["status"]
        try:
            resumed_evidence = None
            if resume:
                checkpoint = load_checkpoint(run, state)
                before = json.loads((inputs / "manifest.json").read_text())
                git_before = checkpoint["git_before"]
                expected = checkpoint["expected"]
                if scan() != expected or git_metadata(roots) != git_before:
                    raise ValueError(
                        "Source/Git changed since checkpoint; continuation refused. Use Restart for fresh planning."
                    )
                if (
                    checkpoint.get("task_hash")
                    and digest(task_text.encode()) != checkpoint["task_hash"]
                ):
                    raise ValueError("Task changed since checkpoint; continuation refused")
                instruction_sources.verify(run, state)
                resume_inputs.verify_preimages(run, state, before)
                stage, plan, feedback = (
                    checkpoint["stage"],
                    checkpoint["plan"],
                    checkpoint["feedback"],
                )
                allowed = checkpoint["allowed"]
                plan_repairs, repair_count = checkpoint["plan_repairs"], checkpoint["repair_count"]
                resumed_evidence = resume_inputs.observations(run, state, stage, roots)
                if stage == "implementer":
                    feedback = dict(
                        previous_feedback=feedback,
                        interrupted=True,
                        instruction="An earlier implementation was interrupted. Inspect current files and preimages, preserve applied changes, and finish only missing approved work. Do not blindly replay edits.",
                    )
                if resume == "extend":
                    resume_inputs.extend_budget(run, stage, config)
                resume_inputs.interrupt_open_records(run, state)
                state.setdefault("continuations", []).append(dict(started_at=clock(), stage=stage))
                state.update(
                    status=RUNNING,
                    summary="Continuing from validated checkpoint",
                    monitoring=dict(
                        max_observed_tokens=config["max_observed_tokens"],
                    ),
                )
                state.pop("finished_at", None)
                save_run(run, state)
            else:
                instruction_sources.capture(run, state, config["source"])
                before, git_before = scan(), git_metadata(roots)
                atomic_json(inputs / "manifest.json", before)
                atomic_json(inputs / "git-metadata.json", git_before)
                expected = dict(before)
                plan, feedback = None, None
                plan_repairs = repair_count = 0
                stage = "planner"
            control.clear_stop(run, resume)
            while True:
                control.check_stop(run)
                control.check_stage(stage, config)
                atomic_json(
                    run / "checkpoint.json",
                    dict(
                        stage=stage,
                        plan=plan,
                        feedback=feedback,
                        allowed=allowed,
                        plan_repairs=plan_repairs,
                        repair_count=repair_count,
                        expected=expected,
                        git_before=git_before,
                        task_hash=digest(task_text.encode()),
                    ),
                )
                if scan() != expected or git_metadata(roots) != git_before:
                    raise ValueError(
                        "Source/Git changed outside the workflow; stopped without rollback"
                    )
                if stage == "check":
                    check_dir, check_record = new_stage(run, state, "check", mode="builtin")
                    active = (check_dir, check_record)
                    state["checks"] = syntax_checks(roots, state["changed_files"], check_dir)
                    failed = any(item["status"] == "FAIL" for item in state["checks"])
                    finish_stage(
                        run,
                        state,
                        check_dir,
                        check_record,
                        "CHECK_FAILED" if failed else "CHECK_COMPLETED",
                        state["checks"],
                    )
                    active = None
                    state["results"]["checks"] = check_record["directory"] + "/result.json"
                    if scan() != expected or git_metadata(roots) != git_before:
                        raise ValueError("Source/Git changed during checks")
                    flow = dict(stage=stage, feedback=feedback, repair_count=repair_count)
                    transitions.checked(flow, state, config["max_repairs"])
                    if state["status"] != RUNNING:
                        return run, state["status"]
                    stage, feedback, repair_count = (
                        flow[key] for key in ("stage", "feedback", "repair_count")
                    )
                    continue
                role = "reviewer" if stage == "plan-reviewer" else stage
                agent_name = "countersign-" + role
                request = prompts.make_request(config, (stage, plan, allowed, feedback), state, run)
                if resume:
                    request += access_recovery.previous_correction(state, stage, roots)
                format_only = False
                recovery, resumed_evidence = resumed_evidence, None
                transport_retries = format_repairs = 0
                access = access_recovery.restore(state, stage)
                retries = config["read_retries"] if stage != "implementer" else 0
                while True:
                    if scan() != expected or git_metadata(roots) != git_before:
                        raise ValueError(
                            "Source/Git changed before retry; recorded evidence is stale"
                        )
                    folder, record = new_stage(
                        run,
                        state,
                        stage,
                        role,
                        "format-repair"
                        if format_only
                        else "access-recovery"
                        if access.count
                        else "research-recovery"
                        if recovery
                        else "model",
                        model=config["models"].get(role),
                    )
                    active = (folder, record)
                    record = attempt_context.prepare(run, record, config, state)
                    prompt = folder / "request.md"
                    evidence_file = folder / "recovery.md" if recovery and not format_only else None
                    attempt_request = request + result_context.execution_context(run, state)
                    if evidence_file:
                        write_evidence(evidence_file, recovery)
                        record["inputs"]["recovery"] = str(evidence_file.relative_to(run))
                        record["recovery_source"] = recovery["source"]
                        attempt_request += (
                            "\nRECOVERY: the preceding read-only attempt ended before a valid result. "
                            "First read this recorded evidence file: "
                            + str(evidence_file)
                            + ". It contains successful tool outputs, not conclusions. The source tree was checked unchanged. "
                            "Do not restart broad discovery: reuse applicable evidence, read only missing ranges, and produce the final result. "
                            "Truncated or omitted output is NOT complete evidence. Do not invent access failures without a tool error.\n"
                        )
                    files = (
                        [safe_file(name, roots) for name in allowed]
                        if stage == "implementer"
                        else []
                    )
                    record["writable_files"] = list(map(str, files))
                    attempt_context.save_request(folder, record, attempt_request, state)
                    edit_base = opencode_api.relative_base(config, roots, files)
                    if edit_base is not None:
                        record["permission_worktree"] = str(edit_base)
                    profile, permissions = make_profile(
                        inputs / "agents" / f"{role}.md",
                        config["destination"],
                        agent_name,
                        roots.values(),
                        artifact_access.model_inputs(run, folder),
                        files,
                        format_only=repair_mode(config, format_only),
                        worktree=edit_base,
                    )
                    profiles.append(profile)
                    atomic_write(folder / "agent.md", profile.read_bytes())
                    verify_permissions(
                        config["command"],
                        next(iter(roots.values())),
                        agent_name,
                        permissions,
                        folder / "permissions.log",
                    )
                    print(
                        "[%s] [%02d] %s model=%s"
                        % (
                            clock(),
                            record["number"],
                            record["directory"],
                            record.get("model", "CLI default"),
                        ),
                        flush=True,
                    )
                    observed = sum(
                        inspect_events(run / s["directory"] / "events.jsonl")["tokens"]["total"]
                        for s in state["stages"]
                    )
                    budget = config["max_observed_tokens"]
                    if budget and observed >= budget:
                        state.update(
                            status="TOKEN_BUDGET_EXCEEDED",
                            summary="Observed token budget reached. Increase the server budget before continuing.",
                        )
                        return run, state["status"]
                    result = run_stage(
                        active,
                        state,
                        dict(
                            format_only=format_only,
                            run=run,
                            roots=roots,
                            profile=profile,
                            allowed=allowed,
                            allowed_paths=files,
                            expected=expected,
                            git_before=git_before,
                            scan=scan,
                            git_metadata=git_metadata,
                        ),
                        dict(
                            command=config["command"],
                            workspace=next(iter(roots.values())),
                            agent=agent_name,
                            model=config["models"].get(role),
                            prompt=prompt,
                            attempt=folder,
                            debug=debug,
                            progress=True,
                            format_only=format_only,
                            runtime=dict(
                                token_budget=max(0, budget - observed) if budget else None,
                                env_allow=config["agent_env_allow"],
                            ),
                        ),
                    )
                    attempt, expected, git_before = attempt_context.record_effect(
                        run, state, record, result, (expected, git_before)
                    )
                    after = scan()
                    delta = changed(expected, after)
                    control.check_delta(
                        delta,
                        allowed if stage == "implementer" else [],
                        git_metadata(roots) == git_before,
                    )
                    for name in delta:
                        safe_file(name, roots)
                    expected = after
                    evidence.refresh(
                        run,
                        folder / "events.jsonl",
                        [
                            *roots.values(),
                            result_context.git_directory(run),
                            run / "00-input/ssh",
                            run / "00-input/local",
                        ],
                    )
                    atomic_json(
                        run / "checkpoint.json",
                        dict(
                            stage=stage,
                            plan=plan,
                            feedback=feedback,
                            allowed=allowed,
                            plan_repairs=plan_repairs,
                            repair_count=repair_count,
                            expected=expected,
                            git_before=git_before,
                            task_hash=digest(task_text.encode()),
                        ),
                    )
                    state["changed_files"] = changed(before, after)
                    if result["status"] == "OK":
                        try:
                            verdict = result_context.parse(
                                result,
                                record,
                                state,
                                dict(roots=roots, run=run, plan=plan),
                            )
                            if stage == "planner":
                                verdict = canonical_plan(verdict, roots)
                                validate_plan(verdict, roots, config["task"], config)
                        except (ValueError, TypeError) as exc:
                            result.update(status="INVALID_RESULT", contract_error=str(exc))
                            attempt.update(status="INVALID_RESULT", contract_error=str(exc))
                            print("  INVALID_RESULT: " + str(exc), flush=True)
                            finish_stage(
                                run, state, folder, record, "INVALID_RESULT", diagnostics=result
                            )
                            active = None
                            if stage != "implementer" and format_repairs < 1:
                                format_repairs += 1
                                format_only = True
                                request = prompts.repair(
                                    result["final_text"],
                                    str(exc),
                                    role,
                                    state.get("contract_version"),
                                    state["requirements"],
                                )
                                continue
                        else:
                            finish_stage(
                                run, state, folder, record, "RESULT_VALID", verdict, result
                            )
                            active = None
                            break
                    else:
                        finish_stage(
                            run, state, folder, record, result["status"], diagnostics=result
                        )
                        active = None
                    if (
                        result["status"] == "BLOCKED_PERMISSION"
                        and stage != "implementer"
                        and not format_only
                        and access.accept(result, config["timeout"])
                    ):
                        recovery = evidence.load_index(run)
                        request += access_recovery.correction(
                            access_recovery.denied_calls(result), roots
                        )
                        print(
                            "  Access denied; continuing with allowed sources (%d/2)"
                            % access.count,
                            flush=True,
                        )
                        continue
                    if (
                        result["status"] in ("TIMEOUT", "INCOMPLETE", "PROCESS_ERROR")
                        and transport_retries < retries
                        and not access.count
                    ):
                        transport_retries += 1
                        if not format_only:
                            recovery = evidence.load_index(run)
                        continue
                    detail = (
                        result.get("contract_error")
                        or "; ".join(result.get("errors", []))
                        or result["status"]
                    )
                    state.update(
                        status=result["status"],
                        summary="Stage " + record["directory"] + " failed: " + detail,
                    )
                    return run, state["status"]
                flow = dict(
                    stage=stage,
                    plan=plan,
                    feedback=feedback,
                    allowed=allowed,
                    plan_repairs=plan_repairs,
                    repair_count=repair_count,
                )
                transitions.advance(
                    flow,
                    state,
                    verdict,
                    f"{record['directory']}/result.json",
                    config["max_repairs"],
                )
                if state["status"] != RUNNING:
                    return run, state["status"]
                stage, plan, feedback = (flow[key] for key in (STAGE, "plan", "feedback"))
                allowed, plan_repairs, repair_count = (
                    flow[key] for key in ("allowed", "plan_repairs", "repair_count")
                )
                if flow.get("effect") == "capture_preimages":
                    for name in allowed:
                        original = safe_file(name, roots)
                        ref = "00-input/preimages/" + name if original.exists() else None
                        if ref:
                            atomic_write(run / ref, original.read_bytes())
                        state[PREIMAGES][name] = ref
                elif flow.get("effect") == "write_diff":
                    write_diff(run, roots, state[PREIMAGES])
        except KeyboardInterrupt:
            current = scan()
            if (
                git_before is not None
                and git_metadata(roots) == git_before
                and all(
                    name in (allowed if stage == "implementer" else [])
                    for name in changed(expected, current)
                )
            ):
                atomic_json(
                    run / "checkpoint.json",
                    dict(
                        stage=stage,
                        plan=plan,
                        feedback=feedback,
                        allowed=allowed,
                        plan_repairs=plan_repairs,
                        repair_count=repair_count,
                        expected=current,
                        git_before=git_before,
                        task_hash=digest(task_text.encode()),
                    ),
                )
            state.update(
                status="INTERRUPTED", summary="Interrupted; changes preserved, no automatic replay"
            )
            return run, state["status"]
        except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
            state.update(status=attempt_context.failure_status(exc), summary=str(exc))
            return run, state["status"]
        finally:
            if active:
                finish_stage(
                    run,
                    state,
                    active[0],
                    active[1],
                    state["status"],
                    diagnostics={"errors": [state.get("summary", "")]},
                )
            try:
                if before is not None:
                    state["changed_files"] = changed(before, scan())
                if state[PREIMAGES]:
                    write_diff(run, roots, state[PREIMAGES])
            except (ValueError, OSError) as exc:
                state["report_error"] = str(exc)
            state["finished_at"] = clock()
            report(run, state)
            for profile in set(profiles):
                profile.unlink(missing_ok=True)
            print("Status: " + state["status"] + "\nReport: " + str(run / "report.md"), flush=True)
