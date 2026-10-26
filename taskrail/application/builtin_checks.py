"""Built-in syntax checks of changed files; nothing from the project is executed."""

import ast
import json
import os
import shutil
import subprocess
import tokenize
from importlib import import_module
from importlib.util import find_spec
from types import MappingProxyType

from taskrail.application.planned_paths import safe_file

SHELL_SECONDS = 30
SKIPPED = "SKIPPED"
CHECK_ERRORS = (ValueError, SyntaxError, OSError, subprocess.TimeoutExpired)
YAML_SUFFIXES = (".yml", ".yaml")


def syntax_checks(roots, names):
    """Check each changed file by its suffix."""
    return [file_check(name, safe_file(name, roots)) for name in names]


def file_check(name, path):
    """Return a PASS, FAIL or SKIPPED record for one file."""
    if not path.exists():
        return dict(file=name, status=SKIPPED, detail="deleted file")
    validator = VALIDATORS.get(path.suffix)
    if validator is None:
        return dict(file=name, status=SKIPPED, detail="No built-in syntax validator")
    try:
        detail = validator(path)
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


def yaml_syntax(path):
    """Compose every document with the safe loader; tags such as !vault are not constructed."""
    yaml = import_module("yaml")
    try:
        list(yaml.compose_all(path.read_text(), Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from error
    return "YAML syntax (PyYAML, no tag construction)"


def optional_validators():
    """The runtime is standard-library only; YAML is checked only where PyYAML exists."""
    if find_spec("yaml") is None:
        return {}
    return dict.fromkeys(YAML_SUFFIXES, yaml_syntax)


VALIDATORS = MappingProxyType(
    {".py": python_syntax, ".json": json_syntax, ".sh": shell_syntax, **optional_validators()}
)
