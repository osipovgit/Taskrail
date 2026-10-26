"""Settings of an installation under the previous project name (Countersign).

The installer moves its folders to the Taskrail names; this rewrites the folder names
inside the kept settings and the service environment. Running it again changes nothing.
"""

import json

# Longest first: the bundled roles live below the release folder.
FOLDERS = (
    ("/.local/share/countersign/current/countersign/", "/.local/share/taskrail/current/taskrail/"),
    ("/.local/share/countersign", "/.local/share/taskrail"),
    ("/.config/countersign", "/.config/taskrail"),
    ("/.local/state/countersign", "/.local/state/taskrail"),
)
PRIVATE_FILE = 0o600


def follow(config):
    """Point kept settings at the Taskrail folders and variables."""
    follow_settings(config / "settings.json")
    environment = config / "service.env"
    if environment.is_file():
        text = environment.read_text()
        if "COUNTERSIGN_" in text:
            environment.write_text(text.replace("COUNTERSIGN_", "TASKRAIL_"))
            environment.chmod(PRIVATE_FILE)


def follow_settings(path):
    """Rewrite the settings only when a previous folder name is in them."""
    if not path.is_file():
        return
    current = json.loads(path.read_text())
    moved = renamed(current)
    if moved != current:
        encoded = json.dumps(moved, indent=2)
        path.write_text(f"{encoded}\n")
        path.chmod(PRIVATE_FILE)


def renamed(setting):
    """The setting with every previous folder name replaced, in nested lists and objects."""
    if isinstance(setting, dict):
        return {key: renamed(entry) for key, entry in setting.items()}
    if isinstance(setting, list):
        return [renamed(entry) for entry in setting]
    if not isinstance(setting, str):
        return setting
    text = setting
    for old, new in FOLDERS:
        text = text.replace(old, new)
    return text
