"""Explicit read-only inputs from the current run, never neighboring histories."""

import re

# Root-level names match opencode 2.x resources relative to the run directory.
PROTECTED_READ_PATTERNS = ("*/.env", "*/.env.*", ".env", ".env.*")


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
        run / "00-input/task.md",
        run / "00-input/preimages",
        run / "00-input/git",
        run / "00-input/ssh",
        run / "00-input/local",
        run / "run.json",
    ]
    paths.extend(result_inputs(run))
    for optional in (folder / "recovery.md", run / "changes.diff"):
        if optional.is_file():
            paths.append(optional)
    return paths


def stage_recoveries(run, state, current):
    """recovery.md files written by earlier attempts of the current record's stage."""
    stage = current["stage"]
    earlier = [record for record in state["stages"] if record.get("stage") == stage]
    references = [record.get("inputs", {}).get("recovery") for record in earlier]
    return [
        run / reference for reference in references if reference and (run / reference).is_file()
    ]


def manifest(run, folder, roots, writable=()):
    """Describe rights without disclosing internal state or widening permissions."""
    return {
        "source_roots": roots,
        "writable_files": list(writable),
        "readable_artifacts": list(map(str, model_inputs(run, folder))),
        "protected_read_patterns": list(PROTECTED_READ_PATTERNS),
        "internal_not_inputs": ["evidence.json", "observations.json", "00-input/git-metadata.json"],
        "git": "Return GIT_REQUEST as the entire final message. It is not a tool call.",
        "remote": "Use ACTION_REQUEST only when advertised; personal approval is required.",
        "local_commands": "Use LOCAL_REQUEST; exact commands need personal approval in the UI.",
        "search": "Search source roots only; never search run directories or protected files.",
    }
