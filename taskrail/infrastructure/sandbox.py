"""Run local commands in a bubblewrap sandbox, so they need no approval.

The host system is visible read-only and home hides its credentials (see
`sandbox_mounts`). Only a writing stage can change its roots; elsewhere writes to them
vanish with the command where the host supports overlays, else they fail. The network
is cut off by a private network namespace where the host allows one, else by a
seccomp socket filter. Without a working bubblewrap nothing runs here.
"""

import contextlib
import functools
import os
import shutil
import subprocess

from taskrail.core import protected_paths
from taskrail.infrastructure import sandbox_mounts, socket_filter

NAMESPACE = socket_filter.NAMESPACE
SOCKET_FILTER = socket_filter.FILTER
PROBE_SECONDS = 10
OVERLAY_PROBE = "/usr"
BASE = (
    "--die-with-parent",
    "--new-session",
    "--unshare-pid",
    "--unshare-ipc",
    sandbox_mounts.READ_ONLY,
    "/",
    "/",
    "--dev",
    "/dev",
    "--proc",
    "/proc",
)
# Graphical sessions stay closed even where their abstract sockets remain reachable.
DESKTOP = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS")


def health():
    """Informational check line: how local commands run here, or why bubblewrap does not."""
    current = mode()
    if current is not None:
        return True, f"Local commands: sandboxed without approval; network cut off by a {current}"
    failures = [f"{kind}: {error}" for kind, error in attempts()]
    reason = "; ".join(failures) or "bwrap not found"
    return True, f"Local commands: each one waits for approval; no sandbox ({reason})"


def executable():
    """bubblewrap from the fixed system search path, never from a project's PATH."""
    return shutil.which("bwrap", path=os.defpath)


@functools.cache
def mode():
    """How this host isolates the network of a sandboxed command, or None."""
    return next((kind for kind, error in attempts() if error is None), None)


@functools.cache
def attempts():
    """Each kind of sandbox tried here, in order, with bubblewrap's error or None."""
    if executable() is None:
        return ()
    tried = []
    for candidate in (NAMESPACE, SOCKET_FILTER):
        tried.append((candidate, probe(candidate)))
        if tried[-1][1] is None:
            break
    return tuple(tried)


@functools.cache
def overlays():
    """Whether roots a stage may not change can take writes that vanish afterwards."""
    current = mode()
    return current is not None and not probe(current, sandbox_mounts.discarded(OVERLAY_PROBE))


def probe(candidate, mounts=()):
    """Why an empty command does not start in this kind of sandbox; None when it does."""
    empty = shutil.which("true", path=os.defpath)
    if empty is None or (candidate == SOCKET_FILTER and socket_filter.program() is None):
        return "unsupported on this host"
    with socket_filter.isolation(candidate) as launch:
        options = [*BASE, *launch["args"], *mounts]
        try:
            completed = subprocess.run(
                [executable(), *options, "--", empty],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=PROBE_SECONDS,
                pass_fds=launch["pass_fds"],
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return str(error)
    if completed.returncode:
        return completed.stderr.strip() or f"exit status {completed.returncode}"
    return None


@contextlib.contextmanager
def command(argv, cwd, roots, writable, protected=protected_paths.DEFAULT_PATTERNS):
    """Popen arguments of the sandboxed command: its argv and inherited descriptors."""
    mounts = [
        *sandbox_mounts.private(),
        *sandbox_mounts.home(),
        *sandbox_mounts.installation(argv[0]),
        *sandbox_mounts.project(roots, writable, protected, overlays()),
    ]
    desktop = [option for name in DESKTOP for option in ("--unsetenv", name)]
    command = [*mounts, *desktop, "--chdir", str(cwd), "--", *argv]
    with socket_filter.isolation(mode()) as launch:
        arguments = [*BASE, *launch["args"], *command]
        yield dict(launch, args=[executable(), *arguments])
