"""Validated local task submissions; no client-controlled commands or settings."""

import fcntl
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from countersign.core.files import atomic_json
from countersign.core.runtime import settings_path
from countersign.web import history, lifecycle, requests


def build_task(payload, runs):
    if not isinstance(payload, dict):
        raise ValueError("The request must be a JSON object")
    fields = (
        "title",
        "goal",
        "criteria",
        "current_behavior",
        "entry_points",
        "constraints",
        "verification",
    )
    if set(payload) - set(fields) - {"roots"}:
        raise ValueError("Unknown task fields; commands and settings cannot be submitted")
    values = {}
    for key in fields:
        value = payload.get(key, "")
        if not isinstance(value, str) or len(value) > 16000 or "\x00" in value:
            raise ValueError("Invalid or oversized field: " + key)
        values[key] = value.strip()
    for key in ("title", "goal", "criteria"):
        if not values[key]:
            raise ValueError("Required field: " + key)
    if len(values["title"]) > 160 or "\n" in values["title"] or "\r" in values["title"]:
        raise ValueError("Title must be one line, at most 160 characters")
    if any(re.search(r"^```countersign-task\s*$", value, re.M) for value in values.values()):
        raise ValueError("The form generates the countersign-task header; do not embed another one")
    if any(history.HISTORY.strip() in field for field in values.values()):
        raise ValueError("Conversation history is reserved for server-generated context")
    entries = payload.get("roots")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
        raise ValueError("Provide between one and eight project roots")
    roots = {}
    resolved_roots = []
    runs = Path(runs).resolve()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"alias", "path"}:
            raise ValueError("Each project needs an alias and path")
        alias, raw = entry["alias"], entry["path"]
        if (
            not isinstance(alias, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", alias)
            or alias in roots
        ):
            raise ValueError(
                "Project aliases must be unique letters, digits, underscores or hyphens"
            )
        if not isinstance(raw, str) or any(char in raw for char in "*?\r\n\x00"):
            raise ValueError("Invalid project path")
        root = Path(raw).expanduser()
        if not root.is_absolute():
            raise ValueError("Use absolute project paths or ~/...")
        root = root.resolve(strict=True)
        if not root.is_dir() or root == Path(root.anchor):
            raise ValueError("Project must be an existing directory, not a filesystem root")
        if root == runs or root in runs.parents or runs in root.parents:
            raise ValueError("Project roots and the run storage must not overlap")
        if any(root == old or root in old.parents or old in root.parents for old in resolved_roots):
            raise ValueError("Project roots must not overlap")
        roots[alias] = str(root)
        resolved_roots.append(root)
    meta = dict(
        roots=roots,
        verification=[line.strip() for line in values["verification"].splitlines() if line.strip()],
    )
    sections = [
        "```countersign-task",
        json.dumps(meta, ensure_ascii=False, indent=2),
        "```",
        "",
        "# " + values["title"],
    ]
    for field, title in (
        ("goal", "Goal"),
        ("current_behavior", "Current behavior"),
        ("criteria", "Acceptance criteria"),
        ("entry_points", "Known entry points"),
        ("constraints", "Additional constraints"),
    ):
        if values[field]:
            sections.extend(["", "## " + title, values[field]])
    sections.extend(
        [
            "",
            "## Workflow rules",
            "Discover related files and the minimal change scope within the declared roots.",
            "Preserve unrelated changes. Use controlled Git access; never hard-reset, clean, rewrite history or force-push. Do not edit Git metadata directly.",
            "Use English for generated explanations, comments, documentation and reports.",
            "The server runs syntax checks and configured verification commands. Report all unexecuted checks as unverified.",
            "Remote actions require the isolated SSH executor and personal approval of exact scripts and targets.",
        ]
    )
    return "\n".join(sections) + "\n", values["title"]


class BusyError(ValueError):
    pass


class TaskLauncher:
    def __init__(self, base, settings=None):
        self.base = Path(base).resolve()
        self.settings = settings_path(settings)
        if settings and not self.settings.is_file():
            raise ValueError("Settings file does not exist")
        self.lock = threading.RLock()
        self.process = None
        self.active_run = None
        self.stopping = False

    def submit(self, payload):
        submission = requests.Submission(payload, self.base)
        if workflow_busy():
            raise BusyError("Wait until the running task stops")
        text, title = build_task(submission.fields, self.base)
        return self.launch(submission.decorate(text), title, restart_from=submission.parent)

    def route(self, path, payload):
        """Keep authenticated task and approval routing in the application boundary."""
        if path == "/api/decision":
            lifecycle.approvals.validate_decision(payload)
            run = history.checked_run(self.base, payload["id"])
            return lifecycle.approvals.decide(run, payload)
        if path == "/api/tasks":
            return self.submit(payload)
        return self.action(payload)

    def action(self, payload):
        requests.validate_action(payload)
        name = payload["id"]
        action = payload["action"]
        run = history.checked_run(self.base, name)
        if action == "restart":
            return dict(id=name, draft=history.task_draft(run))
        if action == "stop":
            return lifecycle.request_stop(run)
        if action == "delete":
            with self.lock:
                if self.process is not None and self.process.poll() is None:
                    raise BusyError("Wait for the active worker to finish")
                return lifecycle.trash_run(self.base, run)
        if workflow_busy():
            raise BusyError("A workflow is running. Wait until it stops.")
        text = (run / "00-input/task.md").read_text(encoding="utf-8")
        title = next(
            (line[2:].strip() for line in text.splitlines() if line.startswith("# ")), name
        )
        lifecycle.require_resumable(run)
        return self.launch(text, title, resume_run=run, extend_budget=action == "resume_budget")

    def busy(self):
        """Keep service shutdown and worker admission mutually exclusive."""
        if self.stopping:
            return True
        return self.process is not None and self.process.poll() is None

    def launch(self, text, title, resume_run=None, restart_from=None, extend_budget=False):
        with self.lock:
            if self.busy():
                raise BusyError("Application is stopping or a task is still running. Try later.")
            if workflow_busy():
                raise BusyError("Another workflow holds the execution lock.")
            name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(4).hex()
            run_name = resume_run.name if resume_run else name
            self.active_run = self.base / run_name
            if (self.base / ".submissions").is_symlink():
                raise ValueError("Submission storage must not be a symlink")
            folder = self.base / ".submissions" / name
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "task.md").write_text(text, encoding="utf-8")
            state = dict(
                id=run_name,
                launch_id=name,
                restart_from=restart_from,
                resume=bool(resume_run),
                title=title,
                status="STARTING",
                summary="Starting the task worker.",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            atomic_json(folder / "launch.json", state)
            argv = worker_command(
                folder,
                resume_run or self.base / name,
                self.settings,
                bool(resume_run),
                extend_budget,
            )
            environment = dict(os.environ)
            package_root = str(Path(__file__).resolve().parents[2])
            environment["PYTHONPATH"] = package_root + (
                os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
            )
            try:
                with (folder / "console.log").open("wb") as output:
                    self.process = subprocess.Popen(
                        argv,
                        cwd=package_root,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                threading.Thread(target=self.process.wait, daemon=True).start()
            except OSError as error:
                state.update(status="LAUNCH_ERROR", summary=str(error))
                atomic_json(folder / "launch.json", state)
            return dict(id=run_name, status=state["status"])


def workflow_busy():
    path = Path.home() / ".local/state/countersign/live.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
    return False


def worker_command(folder, run, settings, resumed, extended):
    """Build trusted flags; neither task text nor model output controls commands."""
    argv = [sys.executable, "-m", "countersign.web.worker", str(folder), str(run)]
    if resumed:
        argv.append("--resume")
    if extended:
        argv.append("--extend-budget")
    if settings.exists():
        argv.extend(["--settings", str(settings)])
    return argv
