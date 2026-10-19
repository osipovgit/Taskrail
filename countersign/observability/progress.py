"""Console progress lines and local timestamps."""

import sys
from datetime import datetime


def say(text):
    """Write one progress line for the CLI or the worker log."""
    sys.stdout.write(f"{text}\n")
    sys.stdout.flush()


def clock():
    """The local time with its offset, to the second."""
    return datetime.now().astimezone().isoformat(timespec="seconds")
