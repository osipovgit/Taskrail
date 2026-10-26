"""Raw check streams are immutable artifacts beside compact results."""

from pathlib import Path

from taskrail.core.files import digest, stream_digest


def stored_output(path, outcome):
    """Large streams stay outside the compact result, with exact content digests."""
    stored = dict(outcome)
    streams = {}
    for name in ("stdout", "stderr", "console", "output"):
        text = stored.pop(name, None)
        if isinstance(text, str):
            location = path.with_suffix(f".{name}.txt")
            location.write_text(text, encoding="utf-8")
            streams[name] = metadata(location, text)
    stored["artifacts"] = streams
    return stored


def metadata(location, text):
    """The compact record binds content and exact byte length."""
    encoded = text.encode()
    signature = digest(encoded)
    return dict(path=str(location), sha256=signature, bytes=len(encoded))


def valid(outcome):
    """A changed or missing raw stream invalidates its evidence bundle."""
    for artifact in outcome.get("artifacts", {}).values():
        path = Path(artifact["path"])
        if path.is_symlink() or not path.is_file():
            return False
        if stream_digest(path) != artifact["sha256"]:
            return False
    return True
