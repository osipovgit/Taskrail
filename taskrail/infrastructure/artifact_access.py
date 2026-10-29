"""Explicit read-only inputs from the current run, never neighboring histories."""

import re

from taskrail.core import prompt_texts, protected_paths
from taskrail.infrastructure import sandbox


def result_inputs(run):
    """Expose validated stage outputs without granting access to logs or profiles."""
    paths = []
    for directory in sorted(run.iterdir()):
        if directory.is_symlink() or not re.fullmatch(r"\d+-[a-z-]+", directory.name):
            continue
        candidate = directory / "result.json"
        if candidate.is_file() and not candidate.is_symlink():
            paths.append(candidate)
    return paths


def model_inputs(run, folder):
    """Single source for the model's readable artifacts and advertised input paths."""
    paths = [
        folder / "request.md",
        folder / "tool-result.md",
        folder / "access.json",
        *task_inputs(run),
        run / "00-input/preimages",
        run / "00-input/git",
        run / "00-input/ssh",
        run / "00-input/local",
        run / "00-input/checks",
        run / "00-input/source-views",
        run / "run.json",
    ]
    paths.extend(result_inputs(run))
    optional_files = (
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
    return {
        "source_roots": roots,
        "writable_files": list(writable),
        "readable_artifacts": list(map(str, model_inputs(run, folder))),
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
