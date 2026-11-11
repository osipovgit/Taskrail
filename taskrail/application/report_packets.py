"""Publish and authenticate immutable, flat packets of historical executor evidence."""

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from taskrail.core import read_hints, schema
from taskrail.core.files import stream_digest
from taskrail.executor import protocol


def qualified(path):
    """The executor prefix separates identical report names from different directories."""
    return ".".join((path.parent.name, path.name))


def signature(paths):
    """Bind flattened, executor-qualified filenames and their verified byte digests."""
    hashes = {qualified(path): sha for path, sha in paths.items()}
    return protocol.fingerprint(hashes) if paths else None


def publish(destination, files, signature):
    """Install the verified packet atomically; retries may reuse the same bytes."""
    schema.require(destination == destination.resolve(), "Invalid report packet path")
    if destination.exists():
        verified(destination, signature)
        return
    destination.parent.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temporary:
        packet = Path(temporary) / "packet"
        packet.mkdir()
        for name, path in files.items():
            shutil.copyfile(path, packet / name)
        verified(packet, signature)
        packet.rename(destination)


def fingerprint(folder):
    """Bind every filename and its exact contents, rejecting missing or redirected inputs."""
    message = "Report packet is missing or redirected"
    schema.require(folder.is_dir() and folder == folder.resolve(), message)
    signatures = {}
    for path in folder.iterdir():
        schema.require(path.is_file() and not path.is_symlink(), message)
        signatures[path.name] = stream_digest(path)
    return protocol.fingerprint(signatures)


def verified(folder, signature):
    """Reject missing, modified, or redirected report data before use."""
    schema.require(fingerprint(folder) == signature, "Plan report evidence changed")


def with_companions(hints, folder):
    """Expose sibling metadata and streams as file pointers, never attached contents."""
    paths = {read_hints.split_hint(hint)[0] for hint in hints}
    companions = sorted(map(str, folder.iterdir()))
    return hints + [name for name in companions if name not in paths]
