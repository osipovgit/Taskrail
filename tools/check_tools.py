"""Fail before linting when the selected Python's tools differ from requirements-dev.txt."""

import sys
from importlib import metadata
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements-dev.txt"


def pins(text):
    """Exact name==version pairs; comments and blank lines carry no requirement."""
    for line in text.splitlines():
        requirement = line.partition("#")[0].strip()
        if requirement:
            name, _, version = requirement.partition("==")
            yield name.strip(), version.strip()


def installed(name):
    """The distribution version installed for this interpreter, not the one on PATH."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def drifted(text):
    """One report line for every pin whose installed version differs."""
    lines = []
    for name, pinned in pins(text):
        current = installed(name)
        if current != pinned:
            lines.append(f"  {name}: {current}, pinned {pinned}\n")
    return lines


def main():
    """Report every drifted pin at once with the command that restores the pinned set."""
    drift = drifted(REQUIREMENTS.read_text())
    if not drift:
        return 0
    python, source = sys.executable, REQUIREMENTS.name
    sys.stderr.write(f"Development tools of {python} differ from {source}:\n")
    sys.stderr.writelines(drift)
    sys.stderr.write(f"Install them with: {python} -m pip install -r {source}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
