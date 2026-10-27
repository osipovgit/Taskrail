"""YAML syntax without a YAML dependency of the service itself.

PyYAML in this Python composes the file in process. Otherwise this Python or a system
python3 does, in isolated mode with a fixed argv, when it imports PyYAML, also from
Taskrail's own package directory where an approved install puts it. Only the safe
composer runs: no tag such as !vault is constructed and nothing in the file executes.
"""

import os
import shutil
import subprocess
import sys
from functools import cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

from taskrail.application.run_locks import STATE

SECONDS = 30
IN_PROCESS = "PyYAML in this Python"
TARGET = Path.home() / STATE / "python"
PROBE = "import sys\nsys.path.insert(0, sys.argv[1])\nimport yaml\n"
SCRIPT = """import sys
sys.path.insert(0, sys.argv[2])
import yaml
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        list(yaml.compose_all(stream, Loader=yaml.SafeLoader))
except yaml.YAMLError as error:
    sys.exit(str(error))
"""
MISSING = "YAML not checked: no Python here has PyYAML"


class Unavailable(Exception):
    """No Python with PyYAML can check the file."""


def syntax(path):
    """The check detail of a valid file; ValueError names a syntax error."""
    checker = source()
    if checker is None:
        raise Unavailable(MISSING)
    if checker == IN_PROCESS:
        compose(path)
    else:
        run(checker, path)
    return f"YAML syntax ({checker}, no tag construction)"


@cache
def source():
    """This Python when it has PyYAML, else a Python that imports it, else None."""
    if find_spec("yaml") is not None:
        return IN_PROCESS
    for python in pythons():
        if completed(python, "-c", PROBE, str(TARGET)).returncode == 0:
            return python
    return None


def pythons():
    """This Python, then the system python3."""
    system = shutil.which("python3", path=os.defpath)
    return [python for python in dict.fromkeys((sys.executable, system)) if python]


def compose(path):
    """Compose every document in process."""
    yaml = import_module("yaml")
    try:
        list(yaml.compose_all(path.read_text(), Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from error


def run(python, path):
    """Compose every document with another Python."""
    finished = completed(python, "-c", SCRIPT, str(path), str(TARGET))
    if finished.returncode:
        raise ValueError(finished.stderr.decode(errors="replace").strip())


def completed(python, *arguments):
    """Run a fixed argv in isolated mode with the default PATH only."""
    return subprocess.run(
        [python, "-I", *arguments],
        env={"PATH": os.defpath},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=SECONDS,
        check=False,
    )
