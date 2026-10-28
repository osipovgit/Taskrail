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
import tempfile

from taskrail.core import protected_paths
from taskrail.infrastructure import sandbox_mounts, socket_filter

NAMESPACE = "network namespace"
SOCKET_FILTER = "socket filter"
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
    """Informational check line: how local commands run on this host."""
    current = mode()
    if current is None:
        return True, "Local commands: no working bubblewrap, so each one waits for approval"
    return True, f"Local commands: sandboxed without approval; network cut off by a {current}"


def executable():
    """bubblewrap from the fixed system search path, never from a project's PATH."""
    return shutil.which("bwrap", path=os.defpath)


@functools.cache
def mode():
    """How this host isolates the network of a sandboxed command, or None."""
    if executable() is None:
        return None
    for candidate in (NAMESPACE, SOCKET_FILTER):
        if probe(candidate):
            return candidate
    return None


@functools.cache
def overlays():
    """Whether roots a stage may not change can take writes that vanish afterwards."""
    current = mode()
    return current is not None and probe(current, sandbox_mounts.discarded(OVERLAY_PROBE))


def probe(candidate, mounts=()):
    """Whether an empty command starts in this kind of sandbox."""
    empty = shutil.which("true", path=os.defpath)
    if empty is None or (candidate == SOCKET_FILTER and socket_filter.program() is None):
        return False
    with isolation(candidate) as launch:
        options = [*BASE, *launch["args"], *mounts]
        try:
            completed = subprocess.run(
                [executable(), *options, "--", empty],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=PROBE_SECONDS,
                pass_fds=launch["pass_fds"],
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
    return completed.returncode == 0


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
    with isolation(mode()) as launch:
        arguments = [*BASE, *launch["args"], *command]
        yield dict(launch, args=[executable(), *arguments])


@contextlib.contextmanager
def isolation(kind):
    """Network isolation options; a seccomp program is read from an inherited file."""
    if kind == NAMESPACE:
        yield dict(args=["--unshare-net"], pass_fds=())
        return
    with tempfile.TemporaryFile() as program:
        program.write(socket_filter.program())
        program.flush()
        program.seek(0)
        descriptor = program.fileno()
        yield dict(args=["--seccomp", str(descriptor)], pass_fds=(descriptor,))
