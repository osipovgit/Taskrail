"""Recognize inline code and ambiguous interpreter options, so their card names them."""

import re
from pathlib import Path

INTERPRETER = re.compile(r"(?:ba|da|z|k)?sh|python[0-9.]*")
SHELL_VALUES = frozenset(("-o", "-O", "+o", "+O", "--rcfile", "--init-file"))
PYTHON_VALUES = frozenset(("-W", "-X", "--check-hash-based-pycs"))
SHELL_LONG = frozenset(
    (
        "--noprofile",
        "--norc",
        "--posix",
        "--verbose",
        "--login",
        "--restricted",
        "--debugger",
        "--dump-strings",
        "--dump-po-strings",
        "--help",
        "--version",
    )
)
PYTHON_LONG = frozenset(("--help", "--help-env", "--help-xoptions", "--help-all", "--version"))
SHELL_FLAGS = frozenset("abefhiklmnprstuvxBCEHPTD")
PYTHON_FLAGS = frozenset("bBdEiIOPqRsSuvVx")
INLINE = "inline"
NEEDS_VALUE = "value"
FLAG = "flag"


def detected(argv):
    """Inline or ambiguous interpreter syntax, including wrapper split strings."""
    split = any(split_string(word) for word in argv)
    if split and any(Path(word).name == "env" for word in argv):
        return True
    for position, word in enumerate(argv):
        name = Path(word).name
        if interpreter(name, argv[position + 1 :]):
            return True
    return False


def split_string(word):
    """GNU env accepts -S inside compact short-option groups such as -vS."""
    if word.startswith("--split-string"):
        return True
    if not word.startswith("-") or word.startswith("--"):
        return False
    return "S" in word[1:]


def interpreter(name, arguments):
    """Only recognized interpreters have the -c contract checked here."""
    if not INTERPRETER.fullmatch(name):
        return False
    return options(arguments, name.startswith("python"))


def options(arguments, python):
    """Stop at a script/module operand; unknown options always need a personal decision."""
    remaining = iter(arguments)
    for argument in remaining:
        if terminal(argument, python):
            return False
        kind = option_kind(argument, python)
        if kind == INLINE:
            return True
        if kind == NEEDS_VALUE and next(remaining, None) is None:
            return True
    return False


def terminal(argument, python):
    """The end of interpreter options; later -c belongs to the script or module."""
    if argument in {"--", "-"} or (python and argument.startswith("-m")):
        return True
    return not argument.startswith(("-", "+"))


def option_kind(argument, python):
    """Classify known switches, consuming their values before examining further options."""
    valued = PYTHON_VALUES if python else SHELL_VALUES
    known = PYTHON_LONG if python else SHELL_LONG
    if argument in valued:
        return NEEDS_VALUE
    if argument in known or (python and argument.startswith(("-W", "-X"))):
        return FLAG
    return short_option(argument, python)


def short_option(argument, python):
    """Classify compact switches; an unknown long option is never guessed."""
    flags = argument[1:]
    if argument.startswith("--"):
        return INLINE
    if "c" in flags:
        return INLINE
    allowed = PYTHON_FLAGS if python else SHELL_FLAGS
    valued = not python and flags.endswith(("o", "O"))
    if valued and set(flags[:-1]) <= allowed:
        return NEEDS_VALUE
    return FLAG if set(flags) <= allowed else INLINE
