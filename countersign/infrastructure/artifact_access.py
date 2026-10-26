"""Explicit read-only inputs from the current run, never neighboring histories."""

import re

from countersign.core import protected_paths


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


def stage_recoveries(run, state, current):
    """recovery.md files written by earlier attempts of the current record's stage."""
    stage = current["stage"]
    earlier = [record for record in state["stages"] if record.get("stage") == stage]
    references = [record.get("inputs", {}).get("recovery") for record in earlier]
    return [
        run / reference for reference in references if reference and (run / reference).is_file()
    ]


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
        "git": "Return GIT_REQUEST as the entire final message. It is not a tool call.",
        "remote": "Use ACTION_REQUEST only when advertised; personal approval is required.",
        "local_commands": "Use LOCAL_REQUEST; the operator approves exact commands.",
        "search": "Search declared roots and exact listed artifact files; never search run directories or protected files.",
    }
