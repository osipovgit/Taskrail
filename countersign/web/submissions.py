"""Detached task workers launched from the browser; different projects run in parallel."""

import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from countersign.core.files import atomic_json
from countersign.core.runtime import settings_path
from countersign.web import history, lifecycle, requests, run_groups
from countersign.web.run_activity import BusyError, require_idle, run_sources
from countersign.web.task_form import build_task

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TASK_FILE = "task.md"
ID = "id"
MARKS = frozenset(("done", "reopen"))


class TaskLauncher:
    """Owns the worker processes it started; the run locks guard every project."""

    def __init__(self, base, settings=None):
        """Workers write runs under base and use the given settings file."""
        self.base = Path(base).resolve()
        self.settings = settings_path(settings)
        if settings and not self.settings.is_file():
            raise ValueError("Settings file does not exist")
        self.lock = threading.RLock()
        self.workers = {}
        self.stopping = False

    def route(self, path, payload):
        """Keep authenticated task and approval routing in the application boundary."""
        if path == "/api/decision":
            lifecycle.approvals.validate_decision(payload)
            run = history.checked_run(self.base, payload["id"])
            return lifecycle.approvals.decide(run, payload)
        if path == "/api/tasks":
            return self.submit(payload)
        return self.action(payload)

    def submit(self, payload):
        """Start a new run unless one of its projects is busy."""
        submission = requests.Submission(payload, self.base)
        text, title = build_task(submission.fields, self.base)
        sources = [
            Path(entry["path"]).expanduser().resolve() for entry in submission.fields["roots"]
        ]
        launch = dict(text=submission.decorate(text), title=title, restart_from=submission.parent)
        return self.launch(launch, sources)

    def action(self, payload):
        """Restart drafts, stop, delete or continue an existing run."""
        requests.validate_action(payload)
        run = history.checked_run(self.base, payload[ID])
        action = payload["action"]
        if action == "restart":
            return dict(id=run.name, draft=history.task_draft(run))
        if action == "stop":
            return lifecycle.request_stop(run)
        if action == "delete":
            return self.delete(run)
        if action in MARKS:
            return run_groups.mark(run, action == "done")
        lifecycle.require_resumable(run)
        launch = continuation(run, action == "resume_budget", payload.get("note"))
        return self.launch(launch, run_sources(run))

    def delete(self, run):
        """Move a stopped run to the trash."""
        with self.lock:
            if run in self.live():
                raise BusyError("Wait for the active worker to finish")
            return lifecycle.trash_run(self.base, run)

    def live(self):
        """Run directory -> sources of the workers that are still running."""
        running = {}
        for run, (process, sources) in self.workers.items():
            if process.poll() is None:
                running[run] = sources
        return running

    def launch(self, launch, sources):
        """Record the launch and start a detached worker process."""
        with self.lock:
            if self.stopping:
                raise BusyError("The application is stopping. Try again later.")
            require_idle(self.live(), launch.get("resume_run"), sources)
            folder, manifest = create_submission(self.base, launch)
            run = self.base / manifest[ID]
            extended = bool(launch.get("extend_budget"))
            process = start_worker(folder, manifest, run, (self.settings, extended))
            if process is not None:
                self.workers[run] = (process, [str(source) for source in sources])
            return dict(id=manifest[ID], status=manifest["status"])


def continuation(run, extended, note):
    """A launch that continues an existing run from its checkpoint."""
    text = (run / "00-input/task.md").read_text(encoding="utf-8")
    title = history.TaskDraft(text).title(run.name)
    return dict(text=text, title=title, resume_run=run, extend_budget=extended, note=note)


def create_submission(base, launch):
    """A launcher folder with the task, an optional note and the launch record."""
    if (base / ".submissions").is_symlink():
        raise ValueError("Submission storage must not be a symlink")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = "{0}-{1}".format(stamp, os.urandom(4).hex())
    folder = base / ".submissions" / name
    folder.mkdir(parents=True, exist_ok=False)
    folder.joinpath(TASK_FILE).write_text(launch["text"], encoding="utf-8")
    if launch.get("note"):
        folder.joinpath("note.md").write_text(launch["note"], encoding="utf-8")
    resumed = launch.get("resume_run")
    manifest = dict(
        id=resumed.name if resumed else name,
        launch_id=name,
        restart_from=launch.get("restart_from"),
        resume=bool(resumed),
        title=launch["title"],
        status="STARTING",
        summary="Starting the task worker.",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    atomic_json(folder / "launch.json", manifest)
    return folder, manifest


def start_worker(folder, manifest, run, options):
    """The worker process, or None after recording a launch error."""
    settings, extended = options
    argv = worker_command(folder, run, settings, manifest["resume"], extended)
    try:
        with folder.joinpath("console.log").open("wb") as output:
            process = subprocess.Popen(
                argv,
                cwd=PACKAGE_ROOT,
                env=worker_environment(),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as error:
        manifest.update(status="LAUNCH_ERROR", summary=str(error))
        atomic_json(folder / "launch.json", manifest)
        return None
    threading.Thread(target=process.wait, daemon=True).start()
    return process


def worker_environment():
    """The service environment with this package importable first."""
    environment = dict(os.environ)
    paths = [str(PACKAGE_ROOT), environment.get("PYTHONPATH", "")]
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, paths))
    return environment


def worker_command(folder, run, settings, resumed, extended):
    """Build trusted flags; neither task text nor model output controls commands."""
    argv = [sys.executable, "-m", "countersign.web.worker", str(folder), str(run)]
    if resumed:
        argv.append("--resume")
    if extended:
        argv.append("--extend-budget")
    if (folder / "note.md").is_file():
        argv.extend(["--note-file", str(folder / "note.md")])
    if settings.exists():
        argv.extend(["--settings", str(settings)])
    return argv
