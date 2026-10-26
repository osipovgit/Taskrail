"""Rebuild one explicitly supported inspection command before remote approval."""

import shlex
from types import MappingProxyType

from taskrail.core.schema import require
from taskrail.interactions import read_grammar

# Exact switches and valued options, using the same parser as local inspection.
COMMANDS = MappingProxyType(
    {
        "df": ("-h -H -i -k -m -P -T -a --human-readable --local", "-t -x --type --exclude-type"),
        "journalctl": (
            "-b -r -q -x --no-pager --utc --system --user --list-boots --disk-usage",
            "-n -u -p -o --lines --unit --priority --output --since --until --boot",
        ),
        "ss": (
            "-a -l -t -u -x -n -p -r -s -e -i -4 -6 --all --listening --numeric --processes",
            "",
        ),
        "ps": ("-e -A -a -f -F -l -w -H --forest", "-p -u -U -o --pid --user --format --sort"),
        "uptime": ("-p -s --pretty --since", ""),
        "uname": ("-a -s -n -r -v -m -p -i -o --all", ""),
        "id": ("-u -g -G -n -r --user --group --groups --name --real", ""),
        "whoami": ("", ""),
        "free": ("-b -k -m -g -h -w -t --bytes --kibi --mebi --gibi --human --wide --total", ""),
        "nproc": ("--all", "--ignore"),
        "lscpu": ("-a -b -c -e -J --all --online --offline --json", ""),
        "lsblk": ("-a -b -f -l -n -p -r -J --all --bytes --fs --list --json", "-o --output"),
        "getent": ("", ""),
        "readlink": ("-e -f -m -n -q -s -v --canonicalize --canonicalize-existing", ""),
        "realpath": (
            "-e -m -s -q --canonicalize-existing --canonicalize-missing",
            "--relative-to --relative-base",
        ),
        "sha256sum": ("-b -t --binary --text", ""),
        "md5sum": ("-b -t --binary --text", ""),
        "dpkg-query": ("-W -l -s -L --show --list --status --listfiles", "-f --showformat"),
    }
)
OPERATIONS = MappingProxyType(
    {
        "systemctl": (
            "status show is-active is-enabled is-failed cat list-units list-unit-files list-timers",
            (
                "--no-pager --plain --all --full --failed --no-legend -a -l",
                "-p --property --type --state",
            ),
        ),
        "docker": (
            "ps images inspect version info logs",
            (
                "-a -q --all --quiet --no-trunc --timestamps --details --size",
                "--format --filter --tail --since --until",
            ),
        ),
    }
)
OPERATOR_CHARACTERS = frozenset("();<>|&")
LISTED = "{0}; {1}; optionally prefixed by sudo or sudo -n"


def inspection(action):
    """The action with its script rebuilt from one validated read-only command."""
    require(not action["files"], "an inspection carries no files")
    script = action["script"].strip()
    require(len(script.splitlines()) == 1, "run exactly one command")
    argv = arguments_of(script)
    check(argv)
    return dict(action, script=f"{shlex.join(argv)}\n")


def arguments_of(script):
    """Split like a shell, refusing operators that would chain or redirect."""
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
    """Unknown commands, options and operation syntax fail before ticket creation."""
    require(bool(argv), "name the command to run")
    program, arguments = argv[0], argv[1:]
    if program == "sudo":
        non_interactive = arguments[:1] == ["-n"]
        check(arguments[int(non_interactive) :])
    elif program == "hostname":
        require(not arguments, "hostname takes no arguments here")
    elif program in OPERATIONS:
        operation(program, arguments)
    else:
        command(program, arguments)


def command(program, arguments):
    """Shared file reads and explicitly specified remote diagnostics."""
    grammar = COMMANDS.get(program)
    if grammar is None:
        read_grammar.operands(program, arguments)
    else:
        read_grammar.parse(arguments, grammar, options_after_paths=True)


def operation(program, arguments):
    """Subcommands are literal operands after global options have been validated."""
    names, grammar = OPERATIONS[program]
    _, operands = read_grammar.parse(arguments, grammar, options_after_paths=True)
    require(bool(operands), "Missing inspection operation")
    require(operands[0] in names.split(), "Unsupported inspection operation")
    # Neither CLI treats -- before an operation as authorization for new options.
    require("--" not in arguments, "Inspection operations do not accept --")


def listed():
    """The listed commands and operations, as instructions and refusals name them."""
    operations = []
    for name, spec in OPERATIONS.items():
        names = "|".join(spec[0].split())
        operations.append(f"{name} {names}")
    programs = [*COMMANDS, *read_grammar.COMMANDS, "find", "hostname"]
    return LISTED.format(", ".join(sorted(programs)), "; ".join(operations))
