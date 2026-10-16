"""Submit exact server actions or inspect the isolated executor."""

import argparse
import json
import sys
from pathlib import Path

from countersign.executor import client


def main():
    """Expose a CLI without transmitting credentials to the orchestrator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("catalog", "submit", "status"))
    parser.add_argument("value", nargs="?")
    parser.add_argument("--key", help="Stable idempotency key for submission retries")
    args = parser.parse_args()
    payload = dict(operation=args.operation)
    if args.operation == "submit":
        if not args.value or not args.key:
            parser.error("submit requires an action JSON file and --key")
        action = json.loads(Path(args.value).read_text(encoding="utf-8"))
        payload.update(key=args.key, action=action)
    elif args.operation == "status":
        payload["id"] = args.value
    response = json.dumps(client.request(payload), ensure_ascii=True, indent=2)
    sys.stdout.write(f"{response}\n")


if __name__ == "__main__":
    main()
