"""Explicit read-only inputs from the current run, never neighboring histories."""

import re

from taskrail.core import prompt_texts, protected_paths
from taskrail.infrastructure import sandbox, stage_scratch


def result_inputs(run):
    """Expose validated stage outputs without granting access to logs or profiles."""
    paths = []
    for directory in sorted(run.iterdir()):
        if directory.is_symlink() or not re.fullmatch(r"\d+-[a-z-]+", directory.name):
            continue
        for name in (
            "result.json",
            "handoff.md",
            "findings.json",
            "validation.json",
            "commit-message.txt",
            "no-change-note.txt",
        ):
            candidate = directory / name
            paths.append(candidate)
    return [path for path in paths if path.is_file() and not path.is_symlink()]


def model_inputs(run, folder):
    """Single source for the model's readable artifacts and advertised input paths."""
    paths = [
        folder / "request.md",
        folder / "tool-result.md",
        folder / "validation.json",
        folder / "access.json",
        *task_inputs(run),
        run / "00-input/preimages",
        run / "00-input/git",
        run / "00-input/remote",
        run / "00-input/local",
        run / "00-input/checks",
        run / "00-input/source-views",
    ]
    for packet in (
        folder / stage_scratch.DIRECTORY,
        run / "00-input/original",
        run / "00-input/dependency-checks",
        run / "00-input/plan-reports",
    ):
        if packet.is_dir() and packet.resolve() == packet:
            paths.append(packet)
    paths.extend(result_inputs(run))
    paths.extend(progress_archives(run))
    optional_files = (
        run / "00-input/findings.json",
        run / "plan.md",
        run / "00-input/parent-task.md",
        run / "00-input/reviewed-plan.json",
        folder / "recovery.md",
        run / "00-input/project-map.md",
        run / "changes.diff",
    )
    for optional in optional_files:
        if optional.is_file() and not optional.is_symlink():
            paths.append(optional)
    return paths


def progress_archives(run):
    """Exact archived notes readable by the active run."""
    paths = sorted(run.joinpath("00-input/progress-archive").glob("*.md"))
    return [path for path in paths if path.is_file() and not path.is_symlink()]


def task_inputs(run):
    """A reviewed child exposes authenticated input, not its untrusted display archive."""
    canonical = run / "00-input/reviewed-task-spec.json"
    if canonical.exists():
        return [canonical] if canonical.is_file() and not canonical.is_symlink() else []
    paths = [run / "00-input/task.md"]
    history = run / "00-input/history.md"
    if history.is_file() and not history.is_symlink():
        paths.append(history)
    return paths


def manifest(run, folder, roots, writable=(), protected=protected_paths.DEFAULT_PATTERNS):
    """Describe rights without disclosing internal state or widening permissions."""
    readable = model_inputs(run, folder)
    initial = (folder / "access.json", folder / "request.md")
    return {
        "source_roots": roots,
        "writable_files": list(writable),
        "readable_artifacts": [str(path) for path in readable if path.exists() or path in initial],
        "protected_read_patterns": list(protected),
        "internal_not_inputs": [
            "evidence.json",
            "observations.json",
            "source-views.json",
            "00-input/git-metadata.json",
        ],
        "git": prompt_texts.text("manifest.git"),
        "remote": prompt_texts.text("manifest.remote"),
        "local_commands": prompt_texts.text(
            "manifest.local.sandbox" if sandbox.mode() else "manifest.local"
        ),
        "search": prompt_texts.text("manifest.search"),
    }
