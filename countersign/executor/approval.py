"""Interactive root approval for exact immutable server actions."""

import argparse
import json
import os
import sys

from countersign.executor import client, transport


def show_json(payload):
    """Render printable JSON without terminal control characters."""
    text = json.dumps(payload, ensure_ascii=True, indent=2)
    sys.stdout.write(f"{text}\n")


def display(ticket):
    """Escape remote-controlled terminal sequences during review."""
    show_json(ticket)
    sys.stdout.write("Exact SSH stdin (JSON escaped for terminal safety):\n")
    show_json(transport.remote_script(ticket["action"]))
    sys.stdout.write(
        "Approval covers the complete script and bundle on ALL listed targets, once.\n"
    )
    sys.stdout.write("A disconnect may leave remote processes running. No automatic rollback.\n")
    sys.stdout.write("Type the full digest to confirm this decision, or Enter to cancel: ")
    sys.stdout.flush()


def main():
    """No noninteractive approval flag and no UI approval endpoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticket")
    parser.add_argument("--reject", action="store_true", help="Reject instead of approving")
    args = parser.parse_args()
    if os.geteuid() != 0 or not sys.stdin.isatty():
        parser.error("Use sudo from your terminal to review and approve this ticket")
    ticket = client.request(dict(operation="status", id=args.ticket))
    sys.stdout.write("Decision: REJECT\n" if args.reject else "Decision: APPROVE\n")
    display(ticket)
    confirmation = sys.stdin.readline().strip()
    if confirmation != ticket["digest"]:
        sys.stdout.write("Not approved.\n")
        return
    payload = dict(
        operation="reject" if args.reject else "approve", id=args.ticket, digest=confirmation
    )
    show_json(client.request(payload))


if __name__ == "__main__":
    main()
