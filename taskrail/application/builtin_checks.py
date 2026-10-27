"""Built-in syntax checks of changed files; nothing from the project is executed."""

import ast
import json
import os
import shutil
import subprocess
import tokenize
from types import MappingProxyType

from taskrail.application import yaml_check
from taskrail.application.planned_paths import safe_file

SHELL_SECONDS = 30
SKIPPED = "SKIPPED"
CHECK_ERRORS = (ValueError, SyntaxError, OSError, subprocess.TimeoutExpired)


def syntax_checks(roots, names):
    """Check each changed file by its suffix."""
    return [file_check(name, safe_file(name, roots)) for name in names]


def file_check(name, path):
    """Return a PASS, FAIL or SKIPPED record for one file."""
    if not path.exists():
        return dict(file=name, status=SKIPPED, detail="deleted file")
    validator = VALIDATORS.get(path.suffix)
    if validator is None:
        kind = path.suffix or "files without a suffix"
        return dict(file=name, status=SKIPPED, detail=f"No built-in syntax validator for {kind}")
    try:
        detail = validator(path)
    except yaml_check.Unavailable as missing:
        return dict(file=name, status=SKIPPED, detail=str(missing))
    except CHECK_ERRORS as error:
        return dict(file=name, status="FAIL", detail=str(error))
    return dict(file=name, status="PASS", detail=detail)


def python_syntax(path):
    """Parse with the declared source encoding; never import or execute."""
    with tokenize.open(path) as stream:
        ast.parse(stream.read(), filename=str(path))
    return "Python syntax (no execution)"


def json_syntax(path):
    """Decode the complete document."""
    json.loads(path.read_text())
    return "JSON syntax"


def shell_syntax(path):
    """Trusted fixed argv; bash -n reads the script without executing it."""
    bash = shutil.which("bash", path=os.defpath)
    if bash is None:
        raise ValueError("bash is not installed")
    completed = subprocess.run(
        [bash, "--noprofile", "--norc", "-n", str(path)],
        env={"PATH": os.defpath},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=SHELL_SECONDS,
        check=False,
    )
    if completed.returncode:
        raise ValueError(completed.stderr.decode(errors="replace"))
    return "bash -n (no execution)"


VALIDATORS = MappingProxyType(
    {
        ".py": python_syntax,
        ".json": json_syntax,
        ".sh": shell_syntax,
        ".yml": yaml_check.syntax,
        ".yaml": yaml_check.syntax,
    }
)
