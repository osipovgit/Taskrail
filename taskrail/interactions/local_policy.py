"""Keep explicit Git, privilege and deployment commands on their controlled routes."""

from pathlib import Path

from taskrail.core import prompt_texts
from taskrail.core.schema import require
from taskrail.interactions import inline_code

REMOTE = frozenset(("ssh", "scp", "sftp", "sudo", "su", "kubectl", "helm", "ansible"))
FIX_OPTIONS = frozenset(
    ("--fix", "--fix-only", "--unsafe-fixes", "--write", "--in-place", "--inplace", "--apply")
)
SED_IN_PLACE = ("-i", "--in-place")


def validate(argv):
    """Approved project code is trusted code, not a substitute for an OS sandbox."""
    command = Path(argv[0]).name
    require(command != "git", prompt_texts.text("validation.local_git"))
    require(command not in REMOTE, prompt_texts.text("validation.local_remote"))
    if command == "ansible-playbook":
        require(
            "--syntax-check" in argv,
            prompt_texts.text("validation.local_playbook"),
        )


def read_only(argv):
    """An inspecting stage cannot ask a tool to rewrite files; nothing runs."""
    for argument in argv[1:]:
        option = argument.split("=", 1)[0]
        require(
            option not in FIX_OPTIONS, prompt_texts.text("validation.inspect_only", command=option)
        )
    if Path(argv[0]).name == "sed":
        edits = any(map(in_place, argv[1:]))
        require(not edits, prompt_texts.text("validation.inspect_only", command="sed -i"))


def in_place(option):
    """A sed option that edits its files."""
    return option.startswith(SED_IN_PLACE)


def inline_script(argv):
    """Inline code or ambiguous interpreter options always need a personal decision."""
    return inline_code.personal(argv)
