"""Inspect the isolated executor: its public catalog or one ticket's status.

Tickets are submitted by the orchestrator workflow, which decides whether a stage may
only inspect servers, and each one still needs root approval before anything runs.
"""

import argparse
import json
import sys

from taskrail.executor import client


def main():
    """Expose a read-only CLI without transmitting credentials to the orchestrator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("catalog", "status"))
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    payload = dict(operation=args.operation)
    if args.operation == "status":
        if not args.value:
            parser.error("status requires a ticket ID")
        payload["id"] = args.value
    response = json.dumps(client.request(payload), ensure_ascii=True, indent=2)
    sys.stdout.write(f"{response}\n")


if __name__ == "__main__":
    main()
