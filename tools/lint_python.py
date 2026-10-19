"""Check Wemake findings against reviewed, source-sensitive technical debt."""

import argparse
import importlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality/wemake-baseline.json"
FORMAT = "--format=%(path)s|%(row)d|%(code)s|%(text)s"


def collect():
    """Run the real plugin; fail closed if it is absent or the output is invalid."""
    importlib.import_module("wemake_python_styleguide")
    command = [sys.executable, "-m", "flake8", "countersign", "tools", FORMAT]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode not in {0, 1} or completed.stderr:
        raise RuntimeError(completed.stderr or completed.stdout or "Flake8 failed")
    return Counter(map(fingerprint, completed.stdout.splitlines()))


def fingerprint(line):
    """File, rule, message and the stripped source line, independent of line numbers."""
    filename, row, rule, message = line.split("|", 3)
    excerpt = source_line(filename, int(row))
    return json.dumps([filename, rule, message, excerpt], ensure_ascii=True)


def source_line(filename, number):
    """The finding's source line, or <module> for module-level findings."""
    if not number:
        return "<module>"
    lines = ROOT.joinpath(filename).read_text().splitlines()
    return lines[number - 1].strip()


def main():
    """Reject new findings; refreshing the baseline is an explicit review action."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-baseline", action="store_true")
    current = collect()
    if parser.parse_args().refresh_baseline:
        return refresh(current)
    return compare(current, Counter(json.loads(BASELINE.read_text())))


def compare(current, previous):
    """Report totals and every finding missing from the baseline."""
    added = current - previous
    counts = [current.total(), added.total(), (previous - current).total()]
    write("Wemake: {0} existing findings; {1} new; {2} removed.".format(*counts))
    for finding, count in added.items():
        write(f"NEW ({count}): {finding}")
    return 1 if added else 0


def refresh(current):
    """Write the reviewed baseline."""
    document = json.dumps(dict(sorted(current.items())), indent=2)
    BASELINE.write_text(f"{document}\n")
    write(f"Baseline refreshed: {current.total()} findings. Review every baseline change.")
    return 0


def write(text):
    """One report line."""
    sys.stdout.write(f"{text}\n")


if __name__ == "__main__":
    sys.exit(main())
