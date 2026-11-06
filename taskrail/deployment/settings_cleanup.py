"""Remove retired settings with an exact private backup; preserve unknown extensions."""

import hashlib
import json
import sys

DIGEST_LENGTH = 16
PRIVATE_FILE = 0o600

OBSOLETE = frozenset(
    (
        "isolation",
        "max_change_lines",
        "max_change_files",
        "max_repairs",
        "read_retries",
        "max_stage_attempts",
        "stage_timeout_seconds",
        "stop_on_provider_limit",
        "max_observed_tokens",
    )
)


def clean(path):
    """Back up before changing a staged configuration, including imported overlays."""
    previous = path.read_bytes()
    options = json.loads(previous)
    removed = sorted(OBSOLETE.intersection(options))
    if not removed:
        return
    backup = backup_path(path, previous)
    if not backup.exists():
        backup.write_bytes(previous)
        backup.chmod(PRIVATE_FILE)
    for key in removed:
        options.pop(key)
    path.write_text(f"{json.dumps(options, indent=2)}\n")
    path.chmod(PRIVATE_FILE)
    sys.stdout.write(
        "Removed obsolete settings: {}; backup: {}\n".format(", ".join(removed), backup.name)
    )


def backup_path(path, previous):
    """One backup per exact original configuration."""
    signature = hashlib.sha256(previous).hexdigest()[:DIGEST_LENGTH]
    return path.with_name(f"{path.name}.backup-{signature}")
