"""One storage format boundary, independent of model and executor contracts."""

import json

from taskrail.core.release import RELEASE_ID
from taskrail.core.schema import require

FORMAT = 3
FORMAT_ERROR = "Unsupported run format; start a new task"
RELEASE_ERROR = "Run was created by a different release; use Restart"


def supported(state):
    """Only the current format is readable by application workflows."""
    return (
        isinstance(state, dict)
        and isinstance(state.get("run_format"), int)
        and state["run_format"] == FORMAT
    )


def validate(state):
    """Fail before interpreting fields from an unsupported run."""
    require(supported(state), FORMAT_ERROR)
    return state


def read(run):
    """Read a current run without following an index symlink."""
    path = run / "run.json"
    require(not path.is_symlink(), "Run index must not be a symlink")
    return validate(json.loads(path.read_text()))


def continuing(state):
    """Same-format restarts are allowed; continuations require this exact release."""
    validate(state)
    require(state.get("release_identity") == RELEASE_ID, RELEASE_ERROR)
