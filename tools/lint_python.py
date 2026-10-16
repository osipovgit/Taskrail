"""Check Wemake findings against reviewed, source-sensitive technical debt."""

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality/wemake-baseline.json"


def collect():
    """Run the real plugin; fail closed if it is absent or the output is invalid."""
    import wemake_python_styleguide  # noqa: F401 -- Require the requested plugin.

    command = [
        sys.executable,
        "-m",
        "flake8",
        "countersign",
        "tools",
        "--format=%(path)s|%(row)d|%(code)s|%(text)s",
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode not in {0, 1} or result.stderr:
        raise RuntimeError(result.stderr or result.stdout or "Flake8 failed")
    findings = Counter()
    for line in result.stdout.splitlines():
        filename, row, rule, message = line.split("|", 3)
        source = (ROOT / filename).read_text().splitlines()
        excerpt = source[int(row) - 1].strip() if int(row) else "<module>"
        key = json.dumps([filename, rule, message, excerpt], ensure_ascii=True)
        findings[key] += 1
    return findings


def main():
    """Reject new findings; refreshing the baseline is an explicit review action."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-baseline", action="store_true")
    args = parser.parse_args()
    current = collect()
    if args.refresh_baseline:
        BASELINE.write_text(json.dumps(dict(sorted(current.items())), indent=2) + "\n")
        print(
            f"Baseline refreshed: {sum(current.values())} findings. Review every baseline change."
        )
        return 0
    previous = Counter(json.loads(BASELINE.read_text()))
    added = current - previous
    removed = previous - current
    print(
        f"Wemake: {sum(current.values())} existing findings; {sum(added.values())} new; {sum(removed.values())} removed."
    )
    for finding, count in added.items():
        print(f"NEW ({count}): {finding}")
    return 1 if added else 0


if __name__ == "__main__":
    sys.exit(main())
