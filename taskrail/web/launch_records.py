"""Keep launch records consistent with the workers that were really started.

A parent links a child run before its worker starts (announce). A record that never
got a worker, because the application stopped in between, is marked as failed on the
next start (recover_launches), so nothing starts it late or a second time.
"""

from taskrail.core.files import atomic_json
from taskrail.web.run_sources import launch_record

LAUNCH_FILE = "launch.json"
LAUNCH_ERROR = "LAUNCH_ERROR"
STATUS = "status"
NOT_STARTED = "The application stopped before this worker started; nothing ran. Start it again."


def announce(folder, manifest, before_start):
    """Let the parent link the run before the worker starts; a failed link starts nothing."""
    if before_start is None:
        return
    try:
        before_start(manifest["id"])
    except BaseException:
        manifest.update(status=LAUNCH_ERROR, summary="The run was not linked; nothing started.")
        atomic_json(folder / LAUNCH_FILE, manifest)
        raise


def recover_launches(base):
    """A launch whose worker never started is recorded as failed, never started late.

    The worker writes RUNNING and its PID first, so a STARTING record without a PID was
    left behind when the application stopped between recording and starting it.
    """
    submissions = base / ".submissions"
    if not submissions.is_dir() or submissions.is_symlink():
        return
    for folder in submissions.iterdir():
        manifest = launch_record(folder)
        if manifest.get(STATUS) == "STARTING" and "pid" not in manifest:
            manifest.update(status=LAUNCH_ERROR, summary=NOT_STARTED)
            atomic_json(folder / LAUNCH_FILE, manifest)
