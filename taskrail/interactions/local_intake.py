"""Turn what a model meant as a local command into the exact request that is checked.

Weak models drop the version or the status, add fields, name the command `command`,
write it as one string or give a relative directory. None of that changes what runs:
the command policy, the sandbox and any approval see the resulting argv and cwd.
"""

import shlex
from pathlib import Path

from taskrail.core import prompt_texts, schema

STATUS = "LOCAL_REQUEST"
COMMAND_KEYS = ("argv", "command", "cmd")
# A command string with these characters needs a shell, as its author wrote it.
SHELL_SYNTAX = frozenset("|&;<>()$`*?[]{}~\n")
NO_REASON = "No reason given"
VERSION = 1
KEPT = ("cwd", "sandbox")
OTHER_ROUTES = frozenset(("root", "action", "jenkins"))


def looks_like(payload):
    """Whether a status-less object is meant as a local command."""
    if not isinstance(payload, dict) or "status" in payload:
        return False
    return OTHER_ROUTES.isdisjoint(payload) and (
        "argv" in payload or ("cwd" in payload and has_command(payload))
    )


def has_command(payload):
    """Whether one of the accepted command keys is present."""
    return any(key in payload for key in COMMAND_KEYS)


def normalized(payload):
    """The request fields the model meant; any other field is dropped."""
    schema.require(
        OTHER_ROUTES.isdisjoint(payload), prompt_texts.text("validation.local_route_conflict")
    )
    reason = payload.get("reason")
    request = dict(
        schema_version=payload.get("schema_version", VERSION),
        status=STATUS,
        argv=command_argv(payload),
        reason=reason if isinstance(reason, str) and reason.strip() else NO_REASON,
    )
    kept = {key: payload[key] for key in KEPT if key in payload}
    return dict(request, **kept)


def command_argv(payload):
    """Resolve aliases only if they describe one command."""
    commands = [arguments(payload[key]) for key in COMMAND_KEYS if key in payload]
    if not commands:
        return None
    schema.require(
        all(command == commands[0] for command in commands[1:]),
        prompt_texts.text("validation.local_command_conflict"),
    )
    return commands[0]


def arguments(command):
    """argv of a command list, or of a command string as a shell would read it."""
    if not isinstance(command, str):
        return command
    if SHELL_SYNTAX.intersection(command):
        return ["bash", "-c", command]
    try:
        return shlex.split(command)
    except ValueError:
        return ["bash", "-c", command]


def located(payload, roots):
    """A missing or relative cwd resolved inside the declared roots where unambiguous."""
    directory = directory_of(payload.get("cwd", ""), roots)
    return payload if directory is None else dict(payload, cwd=str(directory))


def directory_of(cwd, roots):
    """The directory a relative cwd names, or None to keep the request unchanged."""
    if not isinstance(cwd, str) or "\x00" in cwd:
        return None
    if Path(cwd).is_absolute():
        return None
    alias, _, rest = cwd.partition("/")
    named = roots.get(alias)
    if named is not None:
        return Path(named, rest).resolve()
    if len(roots) != 1:
        return None
    single = next(iter(roots.values()))
    return Path(single, cwd).resolve()
