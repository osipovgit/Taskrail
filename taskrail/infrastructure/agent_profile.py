"""Managed opencode profiles: the role text plus engine-owned, closed permissions."""

import json

from taskrail.core import prompt_texts, protected_paths
from taskrail.core.files import atomic_write
from taskrail.infrastructure import profile_rules

FRONTMATTER = "---\n"


def make_profile(source, destination, name, access):
    """Write the profile; access holds roots, readable and writable paths and the worktree.

    Returns the profile path and the rules opencode must report for it.
    """
    permissions = closed_permissions(access)
    instructions = body(source)
    target = destination / f"{name}.md"
    atomic_write(target, profile_text(name, permissions, instructions).encode())
    return target, expected_rules(permissions)


def closed_permissions(access):
    """Glob and grep use patterns, not paths; external directory rights bound their roots."""
    permissions = profile_rules.permissions(
        access["roots"],
        access["readable"],
        access["writable"],
        access.get("worktree"),
        access.get("protected", protected_paths.DEFAULT_PATTERNS),
    )

    if access.get("preserved"):
        base = access.get("worktree") or profile_rules.permission_worktree(
            next(iter(access["roots"]))
        )
        for path in access["preserved"]:
            profile_rules.denied_last(permissions["edit"], profile_rules.read_patterns(path, base))
    return permissions


def profile_text(name, permissions, instructions):
    """JSON frontmatter (valid YAML without a YAML dependency), instructions, runtime rules."""
    front = dict(description=f"Managed Taskrail workflow {name}", mode="primary")
    front["permission"] = permissions
    header = json.dumps(front, ensure_ascii=False, indent=2)
    rules = prompt_texts.text("profile.runtime_rules")
    return f"{FRONTMATTER}{header}\n---\n{instructions}\n\n{rules}\n"


def body(path):
    """The role instructions without their frontmatter."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith(FRONTMATTER):
        return text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid agent frontmatter: {path}")
    return parts[1].lstrip()


def expected_rules(permissions):
    """The rule list opencode must report for the profile."""
    return [
        rule
        for permission, setting in permissions.items()
        for rule in setting_rules(permission, setting)
    ]


def setting_rules(permission, setting):
    """One permission: a single action, or actions by pattern."""
    patterns = setting if isinstance(setting, dict) else {"*": setting}
    return [
        dict(permission=permission, pattern=pattern, action=action)
        for pattern, action in patterns.items()
    ]
