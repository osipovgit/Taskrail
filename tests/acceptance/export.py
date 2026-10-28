"""Export independent live provider acceptance tasks without launching any of them."""

import argparse
import json
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from corpus import CORPUS, fields, materialize, submission, write

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for case in CORPUS["tasks"]:
        base = destination / case["id"]
        roots = materialize(base, case)
        text, _ = submission(fields(case, roots), base / "runs")
        write(base / "task.md", text)
        write(base / "oracle.json", json.dumps(dict(id=case["id"], criteria=case["live_oracle"])))
    print(f"Exported {len(CORPUS['tasks'])} independent tasks to {destination}")


if __name__ == "__main__":
    main()
