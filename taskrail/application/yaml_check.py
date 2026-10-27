"""YAML syntax without a YAML dependency of the service itself.

PyYAML in this Python composes the file in process; otherwise a system python3 that
has it does, with a fixed argv in isolated mode. Only the safe composer runs: no tag
such as !vault is constructed and nothing in the file executes.
"""

import os
import shutil
import subprocess
from functools import cache
from importlib import import_module
from importlib.util import find_spec

SECONDS = 30
IN_PROCESS = "PyYAML in this Python"
SCRIPT = """import sys, yaml
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        list(yaml.compose_all(stream, Loader=yaml.SafeLoader))
except yaml.YAMLError as error:
    sys.exit(str(error))
"""
MISSING = "YAML not checked: PyYAML is in neither this Python nor python3 (install python3-yaml)"


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
    """This Python when it has PyYAML, else a system python3 that has it, else None."""
    if find_spec("yaml") is not None:
        return IN_PROCESS
    python = shutil.which("python3", path=os.defpath)
    if python and completed(python, "-c", "import yaml").returncode == 0:
        return python
    return None


def compose(path):
    """Compose every document in process."""
    yaml = import_module("yaml")
    try:
        list(yaml.compose_all(path.read_text(), Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from error


def run(python, path):
    """Compose every document with the system python3."""
    finished = completed(python, "-c", SCRIPT, str(path))
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


def health():
    """Informational check line: how the check stage validates YAML, if at all."""
    checker = source()
    return True, (f"YAML syntax checks: {checker}" if checker else MISSING)
