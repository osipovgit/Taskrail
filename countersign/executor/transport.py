"""Fixed SSH transport; only the approved payload runs remotely."""

import base64
import os
import shlex
import subprocess
import tempfile
from pathlib import PurePosixPath

KNOWN_HOSTS = "/etc/countersign-executor/known_hosts"
ASKPASS = "/opt/countersign-executor/deploy/ssh-askpass"
OUTPUT_LIMIT = 32000
SSH_TRANSPORT_ERROR = 255
SSH_OPTION = "-o"


def remote_script(action):
    """Materialize the exact reviewed bundle in a private remote directory."""
    if not action["files"]:
        return action["script"]
    lines = [
        "set -eu",
        "COUNTERSIGN_WORK=$(mktemp -d /tmp/countersign-action.XXXXXXXX)",
        "trap 'rm -rf -- \"$COUNTERSIGN_WORK\"' EXIT",
        'cd "$COUNTERSIGN_WORK"',
    ]
    files = dict(action["files"])
    files["action.sh"] = action["script"]
    for name, body in files.items():
        lines.extend(file_commands(name, body))
    lines.append("/bin/sh ./action.sh")
    return "{}\n".format("\n".join(lines))


def file_commands(name, body):
    """Avoid executing file body during bundle creation."""
    return [
        "mkdir -p -- {}".format(shlex.quote(str(PurePosixPath(name).parent))),
        "printf %s "
        + shlex.quote(base64.b64encode(body.encode("utf-8")).decode("ascii"))
        + " | base64 -d > "
        + shlex.quote(name),
    ]


def command(host):
    """Do not inherit caller SSH config, agents, proxies or host-key policy."""
    return [
        "/usr/bin/ssh",
        "-F",
        "/dev/null",
        "-T",
        SSH_OPTION,
        "StrictHostKeyChecking=yes",
        SSH_OPTION,
        f"UserKnownHostsFile={KNOWN_HOSTS}",
        SSH_OPTION,
        "GlobalKnownHostsFile=/dev/null",
        SSH_OPTION,
        "IdentityAgent=none",
        SSH_OPTION,
        "PubkeyAuthentication=no",
        SSH_OPTION,
        "PreferredAuthentications=password",
        SSH_OPTION,
        "NumberOfPasswordPrompts=1",
        SSH_OPTION,
        "ConnectTimeout=15",
        SSH_OPTION,
        "ClearAllForwardings=yes",
        SSH_OPTION,
        "PermitLocalCommand=no",
        "-p",
        str(host["port"]),
        "-l",
        host["username"],
        host["hostname"],
        "/bin/sh -s",
    ]


def environment(host):
    """Expose the password only to the isolated SSH/askpass process."""
    return dict(
        PATH="/usr/bin:/bin",
        HOME="/nonexistent",
        DISPLAY="countersign:0",
        SSH_ASKPASS=ASKPASS,
        SSH_ASKPASS_REQUIRE="force",
        COUNTERSIGN_SSH_PASSWORD=host["password"],
        LANG="C.UTF-8",
    )


def execute(host, action):
    """Bound runtime and captured output; a timeout has uncertain remote effects."""
    with tempfile.TemporaryFile() as output:
        try:
            outcome = subprocess.run(
                command(host),
                input=remote_script(action).encode("utf-8"),
                stdout=output,
                stderr=subprocess.STDOUT,
                env=environment(host),
                timeout=action["timeout_seconds"],
                start_new_session=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return captured(output, None)
        return captured(output, outcome.returncode)


def captured(output, exit_code):
    """Transport loss cannot establish whether remote side effects completed."""
    status = "SUCCEEDED" if exit_code == 0 else "FAILED"
    if exit_code is None or exit_code == SSH_TRANSPORT_ERROR or exit_code < 0:
        status = "UNKNOWN"
    size = output.tell()
    output.seek(max(0, size - OUTPUT_LIMIT), os.SEEK_SET)
    return dict(
        status=status,
        exit_code=exit_code,
        output=output.read().decode("utf-8", "replace"),
        truncated=size > OUTPUT_LIMIT,
    )
