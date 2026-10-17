"""Loopback task dashboard with validated, same-origin task submission."""

import json
import re
import secrets
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from countersign.core.paths import tool_paths
from countersign.observability.progress import clock
from countersign.observability.telemetry import inspect_events
from countersign.web import history, lifecycle
from countersign.web.submissions import BusyError, TaskLauncher, workflow_busy

# Browser scripts served from static/; dashboard modules are fixed, never path-derived.
SCRIPTS = frozenset(
    ("/dashboard.js", "/theme.js")
    + tuple(f"/modules/{name}.js" for name in ("app", "dom", "monitor", "stages", "state"))
)


def contained(base, relative):
    base = Path(base).resolve()
    candidate = base / relative
    if candidate.is_symlink():
        raise ValueError("Symlinks are not served")
    resolved = candidate.resolve()
    if base not in resolved.parents:
        raise ValueError("Path outside runs directory")
    return resolved


def read_json(path, limit=8 * 1024 * 1024):
    if path.stat().st_size > limit:
        raise ValueError("JSON artifact is too large")
    return json.loads(path.read_text(encoding="utf-8"))


def text_tail(path, limit=200000):
    if not path.is_file():
        return {"text": "", "truncated": False}
    with path.open("rb") as stream:
        size = path.stat().st_size
        stream.seek(max(0, size - limit))
        return {"text": stream.read(limit).decode("utf-8", "replace"), "truncated": size > limit}


def public_messages(path):
    # Tool outputs and private reasoning are deliberately not rendered as chat.
    tail = text_tail(path, 2 * 1024 * 1024)
    messages = []
    seen = set()
    clipped = False
    for line in tail["text"].splitlines():
        try:
            event = json.loads(line)
            part = event.get("part", {})
            if event.get("type") != "text" or not isinstance(part.get("text"), str):
                continue
            key = part.get("id")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            clipped = clipped or len(part["text"]) > 30000
            messages.append({"text": part["text"][:30000], "timestamp": event.get("timestamp")})
        except (ValueError, AttributeError, TypeError):
            continue
    return {
        "items": messages[-30:],
        "truncated": tail["truncated"] or clipped or len(messages) > 30,
    }


@lru_cache(maxsize=128)
def historical_telemetry(path, size, mtime):
    return inspect_events(Path(path))


def stage_telemetry(run, directory):
    # JSONL is authoritative after interruption; telemetry.json may lag its last event.
    path = contained(run, directory + "/events.jsonl")
    try:
        stat = path.stat()
        return historical_telemetry(str(path), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return inspect_events(path)


def run_view(base, name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", ".."):
        raise ValueError("Invalid run ID")
    run = contained(base, name)
    submission = contained(base, ".submissions/" + name)
    submissions = Path(base) / ".submissions"
    if submissions.is_dir() and not submissions.is_symlink():
        for folder in sorted(submissions.iterdir(), reverse=True):
            if folder.is_symlink() or not folder.is_dir():
                continue
            try:
                candidate = read_json(contained(folder, "launch.json"))
                if candidate.get("id") == name:
                    submission = folder
                    break
            except (OSError, ValueError, AttributeError):
                pass
    try:
        launch = read_json(contained(submission, "launch.json"))
    except (OSError, ValueError):
        launch = {}
    try:
        state = read_json(contained(run, "run.json"))
    except FileNotFoundError:
        if not launch:
            raise
        state = dict(
            status=launch.get("status"), summary=launch.get("summary"), roots={}, stages=[]
        )
    if not isinstance(launch, dict) or not isinstance(state, dict):
        raise ValueError("Invalid run index")
    if launch.get("status") in ("LAUNCH_ERROR", "INTERRUPTED") and state.get("status") == "RUNNING":
        state = dict(state, status=launch["status"], summary=launch.get("summary", ""))
    if not isinstance(state, dict):
        raise ValueError("Invalid run index")
    stages = []
    for record in state.get("stages", []):
        if not isinstance(record, dict):
            continue
        directory = record.get("directory", "")
        if not re.fullmatch(r"\d{2,}-[a-z-]+", directory):
            continue
        stage = dict(record)
        try:
            stage["result"] = read_json(contained(run, directory + "/result.json"))
        except (OSError, ValueError):
            stage["result"] = None
        stage["result"] = tool_paths(stage["result"], state.get("roots", {}))
        stage["summary"] = tool_paths(stage.get("summary", ""), state.get("roots", {}))
        stage["messages"] = tool_paths(
            public_messages(contained(run, directory + "/events.jsonl")), state.get("roots", {})
        )
        try:
            stage["activity"] = read_json(contained(run, directory + "/activity.json"))
        except (OSError, ValueError):
            stage["activity"] = None
        stage["telemetry"] = dict(stage_telemetry(run, directory))
        stage["telemetry"]["timeline"] = tool_paths(
            stage["telemetry"]["timeline"], state.get("roots", {})
        )
        stages.append(stage)
    return {
        "conversation": history.previous_messages(run)
        if (run / history.TASK_FILE).exists()
        else [],
        "draft": history.task_draft(run) if (run / "run.json").exists() else None,
        "actions": lifecycle.actions(run, state, workflow_busy()),
        "started_at": state.get("started_at") or next((s.get("started_at") for s in stages), None),
        "finished_at": state.get("finished_at"),
        "server_time": clock(),
        "monitoring": state.get("monitoring", {}),
        "execution_jobs": state.get("execution_jobs", []),
        "pending_approval": lifecycle.pending_approval(run),
        "requirements": state.get("requirements", []),
        "id": name,
        "status": state.get("status"),
        "summary": tool_paths(state.get("summary", ""), state.get("roots", {})),
        "roots": state.get("roots", {}),
        "changed_files": tool_paths(state.get("changed_files", []), state.get("roots", {})),
        "unverified": state.get("unverified", []),
        "review_limits": state.get("review_limits", []),
        "metrics": state.get("metrics", {}),
        "stages": stages,
        "task": text_tail(contained(run, "00-input/task.md"))
        if (run / "00-input/task.md").is_file()
        else text_tail(contained(submission, "task.md")),
        "launch": launch,
        "console": text_tail(contained(submission, "console.log"), 30000),
        "report": text_tail(contained(run, "report.md")),
        "diff": text_tail(contained(run, "changes.diff")),
    }


def list_runs(base):
    items = []
    if not base.is_dir():
        return items
    for path in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            state = read_json(contained(path, "run.json"))
            task = history.read_artifact(path, history.TASK_FILE)
            task = task.split(history.HISTORY, 1)[0]
            title = next(
                (line.lstrip("# ").strip() for line in task.splitlines() if line.startswith("# ")),
                path.name,
            )
            items.append(
                {
                    "id": path.name,
                    "title": title,
                    "status": lifecycle.display_status(path, state),
                    "summary": state.get("summary", "")[:500],
                }
            )
        except (OSError, ValueError, AttributeError):
            continue
    known = {item["id"] for item in items}
    submissions = base / ".submissions"
    if submissions.is_dir() and not submissions.is_symlink():
        for folder in submissions.iterdir():
            if folder.name in known or folder.is_symlink() or not folder.is_dir():
                continue
            try:
                launch = read_json(contained(folder, "launch.json"))
                if launch.get("resume"):
                    continue
                items.append(
                    dict(
                        id=folder.name,
                        title=launch["title"],
                        status=launch["status"],
                        summary=launch.get("summary", ""),
                    )
                )
            except (OSError, ValueError, KeyError):
                continue
    return sorted(items, key=lambda item: item["id"], reverse=True)


def make_server(base, port, settings=None, launcher=None):
    base = Path(base).expanduser().resolve()
    launcher = launcher or TaskLauncher(base, settings)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, content, kind="application/json; charset=utf-8"):
            data = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def trusted(self, require_origin=False):
            host = self.headers.get("Host", "")
            expected = (
                "127.0.0.1:%d" % self.server.server_port,
                "localhost:%d" % self.server.server_port,
            )
            origin = self.headers.get("Origin")
            return host in expected and (
                origin == "http://" + host if require_origin or origin else True
            )

        def do_POST(self):
            if not self.trusted(require_origin=True) or not secrets.compare_digest(
                self.headers.get("X-Countersign-Token", ""), token
            ):
                return self.send(
                    403, json.dumps({"error": "Invalid origin or session token. Reload the page."})
                )
            if self.path not in ("/api/tasks", "/api/actions", "/api/decision"):
                return self.send(404, "{}")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, json.dumps({"error": "Expected application/json"}))
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536 or self.headers.get("Transfer-Encoding"):
                    return self.send(
                        413, json.dumps({"error": "Task request must be 1 to 65536 bytes"})
                    )
                self.connection.settimeout(5)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                result = launcher.route(self.path, payload)
                return self.send(202, json.dumps(result))
            except (BusyError, BlockingIOError) as error:
                return self.send(409, json.dumps({"error": str(error)}))
            except (ValueError, OSError, KeyError) as error:
                return self.send(400, json.dumps({"error": str(error)}))

        def do_GET(self):
            host = self.headers.get("Host", "")
            if host not in (
                "127.0.0.1:%d" % self.server.server_port,
                "localhost:%d" % self.server.server_port,
            ):
                return self.send(403, "{}")
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + host:
                return self.send(403, "{}")
            target = urlsplit(self.path)
            try:
                if target.path == "/":
                    return self.send(
                        200,
                        (Path(__file__).parent / "static" / "dashboard.html").read_text(),
                        "text/html; charset=utf-8",
                    )
                if target.path == "/dashboard.css":
                    return self.send(
                        200,
                        (Path(__file__).parent / "static/dashboard.css").read_text(),
                        "text/css; charset=utf-8",
                    )
                if target.path in SCRIPTS:
                    return self.send(
                        200,
                        (Path(__file__).parent / "static" / target.path[1:]).read_text(),
                        "text/javascript; charset=utf-8",
                    )
                if target.path == "/api/session":
                    value = dict(token=token)
                elif target.path == "/api/runs":
                    value = list_runs(base)
                elif target.path == "/api/run":
                    value = run_view(base, parse_qs(target.query).get("id", [""])[0])
                else:
                    return self.send(404, "{}")
                return self.send(200, json.dumps(value, ensure_ascii=False))
            except (OSError, ValueError, KeyError):
                return self.send(
                    404,
                    json.dumps(
                        {"error": "Data is unavailable; the stage may still be writing."},
                        ensure_ascii=False,
                    ),
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(base, port=8787, settings=None):
    server = make_server(base, port, settings=settings)
    print(
        "Countersign: http://127.0.0.1:%d — task dashboard; Ctrl+C stops the server, not active task workers"
        % server.server_port,
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
