"""Fixed SSH transport; only the approved payload runs remotely."""

import base64
import shlex
from pathlib import PurePosixPath

from countersign.executor import streams

KNOWN_HOSTS = "/etc/countersign-executor/known_hosts"
ASKPASS = "/opt/countersign-executor/deploy/ssh-askpass"
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
        f"mkdir -p -- {shlex.quote(str(PurePosixPath(name).parent))}",
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
        *authentication(host),
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


def authentication(host):
    """Either one configured private key or one password prompt; never both."""
    identity = host.get("identity_file")
    if identity:
        options = (
            "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no",
            "PreferredAuthentications=publickey",
            "IdentitiesOnly=yes",
            "BatchMode=yes",
            f"IdentityFile={identity}",
        )
    else:
        options = (
            "PubkeyAuthentication=no",
            "PreferredAuthentications=password",
            "NumberOfPasswordPrompts=1",
        )
    return [argument for option in options for argument in (SSH_OPTION, option)]


def environment(host):
    """Expose a password only to the isolated SSH/askpass process."""
    base = dict(PATH="/usr/bin:/bin", HOME="/nonexistent", LANG="C.UTF-8")
    if "password" not in host:
        return base
    return dict(
        base,
        DISPLAY="countersign:0",
        SSH_ASKPASS=ASKPASS,
        SSH_ASKPASS_REQUIRE="force",
        COUNTERSIGN_SSH_PASSWORD=host["password"],
    )


def execute(host, action):
    """Bound runtime and captured output; a timeout has uncertain remote effects."""
    exit_code, tail = streams.run_bounded(
        command(host),
        remote_script(action).encode("utf-8"),
        environment(host),
        action["timeout_seconds"],
    )
    return captured(tail, exit_code)


def captured(tail, exit_code):
    """Transport loss cannot establish whether remote side effects completed."""
    status = "SUCCEEDED" if exit_code == 0 else "FAILED"
    if exit_code is None or exit_code == SSH_TRANSPORT_ERROR or exit_code < 0:
        status = "UNKNOWN"
    return dict(
        status=status,
        exit_code=exit_code,
        output=tail.text(),
        truncated=tail.size > streams.OUTPUT_LIMIT,
    )
