"""Disposable scenario inputs shared by the explicit suite and live-task exporter."""

import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "fixtures/acceptance/corpus.json"
CORPUS = json.loads(SOURCE.read_text())


def materialize(base, case):
    roots = {}
    for alias in case["roots"]:
        root = base / "projects" / (alias + " project with spaces")
        roots[alias] = root
        for name, content in CORPUS["projects"][alias].items():
            write(root / name, case["seed_overrides"].get(alias + "/" + name, content))
    return roots


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if path.suffix == ".sh":
        path.chmod(0o700)


def fields(case, roots):
    payload = {key: case[key] for key in ("goal", "criteria", "constraints", "verification")}
    payload["title"] = case["id"]
    payload["roots"] = [dict(alias=alias, path=str(roots[alias])) for alias in case["roots"]]
    if case["mode"] in {"answer", "design"}:
        payload["read_only"] = True
    if case["mode"] == "design":
        payload["design"] = True
    if case["mode"] == "split":
        payload["decompose"] = True
    return payload


def submission(payload, runs):
    from taskrail.web import requests, task_form

    request = requests.Submission(payload, runs)
    text, _ = task_form.build_task(request.fields, runs)
    return request.decorate(text), request.delivery["parent_context"]


def path(name, roots):
    alias, relative = name.split("/", 1)
    return Path(roots[alias]) / relative


def snapshot(roots):
    return {
        f"{alias}/{file.relative_to(root)}": file.read_bytes()
        for alias, root in roots.items()
        for file in root.rglob("*")
        if file.is_file() and "__pycache__" not in file.parts
    }
