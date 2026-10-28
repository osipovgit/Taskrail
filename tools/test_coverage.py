"""Explicit coverage measurement of regression and scenario acceptance subprocesses."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUTPUT = BASE / "tmp/coverage"
TIMEOUT = 1200


def coverage(arguments, environment, output=None):
    """Use this interpreter and the repository's configuration in every measurement."""
    command = [sys.executable, "-m", "coverage", *arguments]
    completed = subprocess.run(
        command,
        cwd=BASE,
        env=environment,
        stdout=output,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=TIMEOUT,
    )
    return int(completed.returncode != 0)


def measure(environment):
    """Keep both suites separate and retain diagnostics even when a suite fails."""
    suites = dict(
        regression=["-s", "tests"],
        acceptance=["-s", "tests/acceptance", "-p", "scenario_*.py"],
    )
    status = 0
    for name, arguments in suites.items():
        with (OUTPUT / f"{name}.log").open("w") as output:
            arguments = ["run", "-m", "unittest", "discover", *arguments]
            status = max(status, coverage(arguments, environment, output))
    return status


def main():
    """An isolated HOME and data directory prevent runtime and stale-measurement drift."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="taskrail-coverage-") as directory:
        environment = dict(
            os.environ,
            HOME=directory,
            PYTHON=sys.executable,
            PYTHONPATH=os.pathsep.join((str(BASE), str(BASE / "tests"))),
            COVERAGE_FILE=str(Path(directory) / ".coverage"),
            COVERAGE_RCFILE=str(BASE / ".coveragerc"),
        )
        status = measure(environment)
        for command in (["combine"], ["json"], ["html"], ["report"]):
            status = max(status, coverage(command, environment))
    sys.stdout.write(f"Coverage reports and separate suite logs: {OUTPUT}\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
