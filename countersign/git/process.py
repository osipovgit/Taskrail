"""Run Git with a fixed executable, disabled hooks and no shell interpretation."""

import os
import shutil
from types import MappingProxyType

from countersign.core.schema import require
from countersign.git import transport

ENVIRONMENT = MappingProxyType(
    {
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_EDITOR": "false",
        "GIT_SEQUENCE_EDITOR": "false",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "file:https:ssh",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_LITERAL_PATHSPECS": "1",
    }
)
OPTIONS = (
    f"core.hooksPath={os.devnull}",
    "core.fsmonitor=false",
    "merge.autoStash=false",
    "gc.auto=0",
    "maintenance.auto=false",
    "core.pager=cat",
    "diff.external=",
    "commit.gpgSign=false",
    "tag.gpgSign=false",
    "credential.helper=",
    "core.sshCommand=ssh -oBatchMode=yes -oStrictHostKeyChecking=yes",
)


def environment():
    """Ignore inherited Git command/config overrides, preserving normal OS variables."""
    inherited = dict(os.environ)
    for key in os.environ:
        if key.startswith("GIT_"):
            inherited.pop(key)
    inherited.update(ENVIRONMENT)
    return inherited


def invoke(root, arguments, settings=()):
    """Internal, already validated argv only; output is data, never executable text."""
    executable = shutil.which("git", path=os.defpath)
    require(bool(executable), "Git is not installed on the orchestrator host")
    if arguments[0] in {"log", "show", "diff"}:
        arguments = [arguments[0], "--no-ext-diff", "--no-textconv", *arguments[1:]]
    if arguments[0] == "reflog":
        arguments = ["reflog", "show", *arguments[1:]]
    if arguments[0] == "blame":
        arguments = ["blame", "--no-textconv", *arguments[1:]]
    options = [token for setting in (*OPTIONS, *settings) for token in ("-c", setting)]
    return transport.run([executable, "--no-pager", *options, *arguments], root, environment())


def checked(root, arguments):
    """Internal probes must succeed before authorizing a write."""
    outcome = invoke(root, arguments)
    require(outcome.returncode == 0, outcome.stderr or "Git preflight failed")
    return outcome.stdout


def filter_settings(root):
    """Disable repository-defined filters, including executable process filters."""
    outcome = invoke(
        root,
        [
            "config",
            "--name-only",
            "--get-regexp",
            r"^(filter\..*\.(clean|smudge|process|required)|merge\..*\.driver)$",
        ],
    )
    require(outcome.returncode in {0, 1}, "Cannot inspect Git filter configuration")
    settings = []
    for key in outcome.stdout.splitlines():
        suffix = "=false" if key.endswith((".required", ".driver")) else "="
        settings.append(key + suffix)
    return settings
