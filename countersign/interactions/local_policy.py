"""Keep explicit Git, privilege and deployment commands on their controlled routes."""

import re
from pathlib import Path

from countersign.core.schema import require

REMOTE = frozenset(("ssh", "scp", "sftp", "sudo", "su", "kubectl", "helm", "ansible"))
FIX_OPTIONS = frozenset(
    ("--fix", "--fix-only", "--unsafe-fixes", "--write", "--in-place", "--inplace", "--apply")
)
SED_IN_PLACE = ("-i", "--in-place")
INSPECT_ONLY = "this stage may only inspect or verify; request the command without it"
INTERPRETER = re.compile(r"(?:ba|da|z|k)?sh|python[0-9.]*")
# Interpreter options that take the next argument as their value, or end its options.
VALUED = frozenset(("-W", "-X", "-o", "-O", "+o", "+O"))
STOPS = frozenset(("--", "-m"))
OPTION = ("-", "+")


def validate(argv):
    """Approved project code is trusted code, not a substitute for an OS sandbox."""
    command = Path(argv[0]).name
    require(command != "git", "Use GIT_REQUEST so Git policy remains enforced")
    require(
        command not in REMOTE, "Use the isolated SSH executor for privileged or remote operations"
    )
    if command == "ansible-playbook":
        require(
            "--syntax-check" in argv,
            "Only syntax checks are local; execute playbooks through the SSH approval route",
        )


def read_only(argv):
    """An inspecting stage cannot ask a tool to rewrite files; nothing runs."""
    for argument in argv[1:]:
        option = argument.split("=", 1)[0]
        require(option not in FIX_OPTIONS, f"{option} rewrites files; {INSPECT_ONLY}")
    if Path(argv[0]).name == "sed":
        edits = any(map(in_place, argv[1:]))
        require(not edits, f"sed -i rewrites files; {INSPECT_ONLY}")


def in_place(option):
    """A sed option that edits its files."""
    return option.startswith(SED_IN_PLACE)


def inline_script(argv):
    """A shell or Python given code with -c, which the argv[0] checks cannot review.

    Wrappers such as `env`, `timeout` or `xargs` do not hide it; words are split on
    whitespace so `env -S "bash -c ..."` counts too.
    """
    words = [word for argument in argv for word in argument.split()]
    for position, word in enumerate(words):
        interpreter = INTERPRETER.fullmatch(Path(word).name)
        if interpreter and code_option(words[position + 1 :]):
            return True
    return False


def code_option(options):
    """True when the interpreter's own options, before its first operand, include -c."""
    previous = ""
    for option in options:
        if operand(option, previous):
            return False
        if short_options(option) and "c" in option[1:]:
            return True
        previous = option
    return False


def short_options(option):
    """A cluster of single-letter options such as -ec or +x."""
    return option.startswith(OPTION) and not option.startswith("--")


def operand(option, previous):
    """The interpreter's first operand, or an option after which no -c can follow."""
    if option in STOPS:
        return True
    return not option.startswith(OPTION) and previous not in VALUED
