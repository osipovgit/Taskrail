"""Locate a run's index and launcher record, including runs that never started."""

import re

from countersign.web.run_files import contained, read_json

STAGE_DIRECTORY = re.compile(r"\d{2,}-[a-z-]+")
LAUNCH_STOPS = frozenset(("LAUNCH_ERROR", "INTERRUPTED"))
LAUNCH_FILE = "launch.json"
STATUS = "status"
SUMMARY = "summary"


def find_submission(base, name):
    """The launcher folder whose record names this run; restarts use another folder."""
    default = contained(base, f".submissions/{name}")
    submissions = base / ".submissions"
    if not submissions.is_dir() or submissions.is_symlink():
        return default
    for folder in sorted(submissions.iterdir(), reverse=True):
        if submission_id(folder) == name:
            return folder
    return default


def submission_id(folder):
    """The run ID recorded by a launcher folder, if readable."""
    if folder.is_symlink() or not folder.is_dir():
        return None
    try:
        launch = read_json(contained(folder, LAUNCH_FILE))
    except (OSError, ValueError):
        return None
    return launch.get("id") if isinstance(launch, dict) else None


def launch_record(submission):
    """The launcher record, or an empty record."""
    try:
        return read_json(contained(submission, LAUNCH_FILE))
    except (OSError, ValueError):
        return {}


def run_state(run, launch):
    """The run index; a launch that failed before the index exists still has a state."""
    try:
        state = read_json(contained(run, "run.json"))
    except FileNotFoundError:
        if not launch:
            raise
        state = dict(roots={}, stages=[])
        state.update(status=launch.get(STATUS), summary=launch.get(SUMMARY))
    if not isinstance(launch, dict) or not isinstance(state, dict):
        raise ValueError("Invalid run index")
    if launch.get(STATUS) in LAUNCH_STOPS and state.get(STATUS) == "RUNNING":
        state = dict(state, status=launch[STATUS])
        state[SUMMARY] = launch.get(SUMMARY, "")
    return state


def valid_record(record):
    """A stage record with a well-formed directory name."""
    if not isinstance(record, dict):
        return False
    return bool(STAGE_DIRECTORY.fullmatch(record.get("directory", "")))
