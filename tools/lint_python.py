"""Run Wemake through Flake8 on the project sources; any finding fails the check."""

import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Fail closed when the plugin is absent; Flake8 reports every finding itself."""
    importlib.import_module("wemake_python_styleguide")
    command = [sys.executable, "-m", "flake8", "taskrail", "tools"]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
