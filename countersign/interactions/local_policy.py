"""Keep explicit Git, privilege and deployment commands on their controlled routes."""

from pathlib import Path

from countersign.core.schema import require

REMOTE = frozenset(("ssh", "scp", "sftp", "sudo", "su", "kubectl", "helm", "ansible"))


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
