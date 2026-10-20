"""Requests that only read inside the declared roots run without a personal decision.

Reads and a fixed set of listing and reading commands qualify when every path stays
inside a declared root and away from protected files. Anything else, including an
unknown option, still goes to the operator.
"""

from fnmatch import fnmatch
from pathlib import Path
from types import MappingProxyType

from countersign.infrastructure.artifact_access import PROTECTED_READ_PATTERNS
from countersign.interactions import access

FOLLOW = ("-L", "--dereference")
# Command -> options that execute, write, follow links outside, recurse into protected files or never end.
COMMANDS = MappingProxyType(
    {
        "ls": FOLLOW,
        "du": FOLLOW,
        "stat": FOLLOW,
        "wc": ("--files0-from",),
        "cat": (),
        "head": (),
        "tail": ("-f", "-F", "--follow", "--retry"),
        "grep": (
            "-r",
            "-R",
            "-d",
            "-f",
            "--recursive",
            "--dereference-recursive",
            "--directories",
            "--file",
        ),
        "find": (
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-delete",
            "-fprint",
            "-fprint0",
            "-fprintf",
            "-fls",
            "-L",
            "-follow",
        ),
    }
)


def request(payload, roots):
    """True for reads, Jenkins reads and listed commands that stay inside the roots."""
    status = payload.get("status")
    if status == "ACCESS_REQUEST":
        return reads(payload["calls"], roots)
    if status == "LOCAL_REQUEST":
        return command(payload, roots)
    return status == "JENKINS_REQUEST"


def command(payload, roots):
    """A listed command whose options are safe and whose paths stay inside the roots."""
    argv = payload["argv"]
    if argv[0] not in COMMANDS:
        return False
    options, paths = split(argv[1:])
    if not all(allowed(argv[0], option) for option in options):
        return False
    cwd = Path(payload["cwd"])
    return all(inside(cwd / path, roots) for path in paths)


def reads(calls, roots):
    """Read and search calls that target canonical paths inside the roots."""
    try:
        paths = [access.target(call, roots) for call in calls]
    except ValueError:
        return False
    return bool(paths) and all(inside(path, roots) for path in paths)


def split(arguments):
    """(options, operands); everything after "--" is an operand."""
    if "--" in arguments:
        end = arguments.index("--")
        options, operands = split(arguments[:end])
        return options, [*operands, *arguments[end + 1 :]]
    options = [argument for argument in arguments if argument.startswith("-")]
    return options, [argument for argument in arguments if not argument.startswith("-")]


def allowed(program, option):
    """find predicates are whole words; other commands also bundle short letters."""
    forbidden = COMMANDS[program]
    if "/" in option.partition("=")[2]:
        return False
    if program == "find" or option.startswith("--"):
        return option.split("=", 1)[0] not in forbidden
    letters = {f"-{letter}" for letter in option[1:]}
    return not letters.intersection(forbidden)


def inside(candidate, roots):
    """A path that resolves inside a declared root and is not a protected file."""
    path = Path(candidate).resolve()
    if any(fnmatch(str(path), pattern) for pattern in PROTECTED_READ_PATTERNS):
        return False
    return any(path.is_relative_to(root) for root in roots.values())
