"""One storage format boundary, independent of model and executor contracts."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from taskrail.core.schema import require

FORMAT = 2
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


@lru_cache(maxsize=1)
def release_identity():
    """Identify shipped executable code and instructions, independent of install path."""
    root = Path(__file__).resolve().parents[1]
    signature = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".json", ".md"}:
            signature.update(str(path.relative_to(root)).encode())
            signature.update(path.read_bytes())
    return signature.hexdigest()


def continuing(state):
    """Same-format restarts are allowed; continuations require this exact release."""
    validate(state)
    require(state.get("release_identity") == release_identity(), RELEASE_ERROR)
