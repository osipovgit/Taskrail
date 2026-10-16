"""Parse a deliberately bounded Git grammar before starting any process."""

import re
from types import MappingProxyType

from countersign.core.schema import require

READ_FLAGS = MappingProxyType(
    {
        "log": "--oneline --stat --name-only --name-status --patch -p --all --first-parent --no-merges --reverse --format --pretty --max-count -n --since --until",
        "show": "--stat --name-only --name-status --patch -p --format --pretty --no-patch -s",
        "diff": "--stat --name-only --name-status --cached --staged --check --patch -p --numstat",
        "status": "--short -s --porcelain --branch -b --untracked-files",
        "reflog": "--oneline --format --max-count -n",
        "rev-parse": "--show-toplevel --show-prefix --verify --is-inside-work-tree --git-dir",
        "ls-files": "--stage --cached --modified --deleted --others --exclude-standard",
        "ls-tree": "-r --name-only --long",
        "blame": "--line-porcelain --porcelain -L",
        "describe": "--tags --always --long --dirty",
        "merge-base": "--is-ancestor --all",
        "cat-file": "-p -t -s",
    }
)
VALUE_FLAGS = frozenset(("--format", "--pretty", "--max-count", "-n", "--since", "--until", "-L"))
REFLOG_WRITES = frozenset(("expire", "delete", "drop", "write"))
WRITERS = frozenset(("add", "commit", "revert", "cherry-pick", "merge", "fetch", "push"))


def validate(argv, role):
    """No aliases, global options, shell strings, abbreviations or unknown commands."""
    require(isinstance(argv, list) and bool(argv), "Git argv must be a nonempty list")
    require(
        all(isinstance(arg, str) and arg and "\x00" not in arg for arg in argv),
        "Invalid Git argument",
    )
    command = argv[0]
    if command in READ_FLAGS:
        read_arguments(argv)
        return False
    if argv in [["branch"], ["branch", "--all"], ["tag"], ["remote", "-v"]]:
        return False
    require(role == "implementer", "This role has read-only Git access")
    require(command in WRITERS, "Unsupported or prohibited Git operation")
    write_arguments(argv)
    return True


def read_arguments(argv):
    """Only explicitly listed read options may reach Git."""
    flags = READ_FLAGS[argv[0]].split()
    pending = False
    for argument in argv[1:]:
        if pending:
            require(not argument.startswith("-"), "Missing Git option value")
            pending = False
        elif argument == "--":
            flags = []
        else:
            pending = read_option(argument, flags, argv[0])
    require(not pending, "Missing Git option value")
    if argv[0] == "reflog":
        require(
            not REFLOG_WRITES.intersection(argv[1:]),
            "Reflog modification is forbidden",
        )


def read_option(argument, flags, command):
    """Do not admit output destinations, external programs or abbreviated flags."""
    if not argument.startswith("-"):
        return False
    flag, separator, _ = argument.partition("=")
    numeric = bool(re.fullmatch(r"-\d+", argument))
    numeric = numeric and command in {"log", "reflog"}
    require(flag in flags or numeric, f"Unsupported Git read option: {argument}")
    return flag in VALUE_FLAGS and not separator


def write_arguments(argv):
    """Supported writes cannot replace commits, run scripts or force remote updates."""
    command, *arguments = argv
    if command == "add":
        require(len(arguments) > 1, "Use add -- <explicit files>")
        require(arguments[0] == "--", "Use add -- <explicit files>")
    elif command == "commit":
        require(len(arguments) == 2, "Use commit -m <message>; amend is forbidden")
        require(arguments[0] == "-m", "Use commit -m <message>; amend is forbidden")
    elif command in {"revert", "cherry-pick", "merge"}:
        commit_arguments(argv)
    else:
        remote_arguments(argv)


def commit_arguments(argv):
    """Apply a commit without resetting refs, editing the message or rewriting history."""
    command, *arguments = argv
    prefix = "--ff-only" if command == "merge" else "--no-edit"
    require(len(arguments) == 2, f"Use {command} {prefix} <full commit hash>")
    require(arguments[0] == prefix, f"Use {command} {prefix} <full commit hash>")
    require(
        bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", arguments[-1])),
        "Use an observed full commit hash",
    )


def remote_arguments(argv):
    """Require named remotes and an explicit, non-forced branch destination."""
    expected = 2 if argv[0] == "fetch" else 3
    require(len(argv) == expected, "Invalid Git remote request")
    require(
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", argv[1])), "Use a configured remote name"
    )
    if argv[0] == "push":
        require(
            bool(re.fullmatch(r"HEAD:refs/heads/[A-Za-z0-9][A-Za-z0-9_./-]*", argv[2])),
            "Only explicit non-forced HEAD branch pushes are supported",
        )
