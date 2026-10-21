"""Read-only SSH inspection before the operator confirms a change.

Until then an SSH action runs exactly one listed command that only reads server state,
optionally through sudo. The script is parsed into arguments and rebuilt with every
argument quoted, so shell syntax in it stays literal and cannot start another command.
"""

import shlex
from types import MappingProxyType

from countersign.core.schema import require

NONE = frozenset()
FOLLOW = frozenset(("-f", "--follow"))
REMOTE_HOST = frozenset(("-H", "--host", "-M", "--machine"))
# Command -> options that write, execute, follow forever or reach other hosts.
COMMANDS = MappingProxyType(
    {
        "cat": NONE,
        "head": NONE,
        "tail": FOLLOW | {"-F", "--retry"},
        "ls": NONE,
        "stat": NONE,
        "du": NONE,
        "df": NONE,
        "wc": NONE,
        "grep": NONE,
        "find": frozenset(
            ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0")
            + ("-fprintf", "-fls")
        ),
        "journalctl": FOLLOW
        | REMOTE_HOST
        | {"--rotate", "--flush", "--sync", "--relinquish-var", "--smart-relinquish-var"}
        | {"--vacuum-size", "--vacuum-time", "--vacuum-files", "--setup-keys"}
        | {"--update-catalog"},
        "ss": frozenset(("-K", "--kill", "-D", "--diag")),
        "ps": NONE,
        "uptime": NONE,
        "uname": NONE,
        "id": NONE,
        "whoami": NONE,
        "free": NONE,
        "nproc": NONE,
        "lscpu": NONE,
        "lsblk": NONE,
        "getent": NONE,
        "readlink": NONE,
        "realpath": NONE,
        "sha256sum": NONE,
        "md5sum": NONE,
        "dpkg-query": NONE,
    }
)
# Command -> (options forbidden with any operation, operation -> its forbidden options).
OPERATIONS = MappingProxyType(
    {
        "systemctl": (
            REMOTE_HOST,
            dict.fromkeys(
                ("status", "show", "is-active", "is-enabled", "is-failed", "cat")
                + ("list-units", "list-unit-files", "list-timers"),
                NONE,
            ),
        ),
        "docker": (
            frozenset(("-H", "--host", "-c", "--context", "--config")),
            dict(ps=NONE, images=NONE, inspect=NONE, version=NONE, info=NONE, logs=FOLLOW),
        ),
    }
)
# Commands that change state when given arguments.
BARE = frozenset(("hostname",))
SUDO = "sudo"
OPERATOR_CHARACTERS = frozenset("();<>|&")
LISTED = "{0}; {1}; optionally prefixed by sudo or sudo -n"


def inspection(action):
    """The action with its script rebuilt from one validated read-only command."""
    require(not action["files"], "an inspection carries no files")
    script = action["script"].strip()
    require(len(script.splitlines()) == 1, "run exactly one command")
    argv = arguments_of(script)
    check(argv)
    return dict(action, script="{0}\n".format(shlex.join(argv)))


def arguments_of(script):
    """Split like a shell, but refuse unquoted operators that would chain or redirect."""
    lexer = shlex.shlex(script, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        argv = list(lexer)
    except ValueError as error:
        raise ValueError(f"the command cannot be parsed: {error}") from error
    for token in argv:
        require(bool(set(token) - OPERATOR_CHARACTERS), f"shell operator {token} is not allowed")
    return argv


def check(argv):
    """A listed command whose options only read."""
    require(bool(argv), "name the command to run")
    program, arguments = argv[0], argv[1:]
    if program == SUDO:
        non_interactive = arguments[:1] == ["-n"]
        check(arguments[int(non_interactive) :])
        return
    if program in BARE:
        require(not arguments, f"{program} takes no arguments here")
        return
    forbidden = forbidden_options(program, arguments)
    for option in options(arguments):
        require(not blocked(program, option, forbidden), f"{program} {option} is not read-only")


def forbidden_options(program, arguments):
    """The options a listed command or operation must not use."""
    if program not in OPERATIONS:
        require(program in COMMANDS, f"{program} is not a listed read-only command")
        return COMMANDS[program]
    general, operations = OPERATIONS[program]
    operation = next((name for name in arguments if not name.startswith("-")), "")
    require(operation in operations, f"{program} {operation} is not a listed read-only operation")
    return general | operations[operation]


def options(arguments):
    """Arguments before "--" that start with a dash."""
    end = arguments.index("--") if "--" in arguments else len(arguments)
    return [argument for argument in arguments[:end] if argument.startswith("-")]


def blocked(program, option, forbidden):
    """find predicates are whole words; other commands also bundle short letters."""
    name = option.split("=", 1)[0]
    if program == "find" or name.startswith("--"):
        return name in forbidden
    return bool({f"-{letter}" for letter in name[1:]} & forbidden)


def listed():
    """The listed commands and operations, as instructions and refusals name them."""
    operations = []
    for name, (_, names) in OPERATIONS.items():
        operations.append("{0} {1}".format(name, "|".join(names)))
    commands = ", ".join(sorted([*COMMANDS, *BARE]))
    return LISTED.format(commands, "; ".join(operations))
