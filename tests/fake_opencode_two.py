"""A 2.x subprocess transport around the scripted workflow decisions, without a provider."""

import json
import os
import subprocess
import sys
from pathlib import Path


def agents(profiles):
    entries = []
    for path in sorted(profiles.glob("taskrail-*.md")):
        header = json.loads(path.read_text().split("---")[1])
        rules = []
        for permission, value in header["permission"].items():
            for pattern, action in value.items() if isinstance(value, dict) else [("*", value)]:
                name = {"bash": "shell", "task": "subagent"}.get(permission, permission)
                rules.append(dict(action=name, resource=pattern, effect=action))
        entries.append(dict(id=path.stem, mode="primary", permissions=rules))
    return entries


def translate(event):
    if event.get("type") == "tool_use":
        part = event["part"]
        part["partID"] = part["id"]
        part["id"] = part.get("callID", part["id"])
        state = part["state"]
        arguments = state.get("input", {})
        if "filePath" in arguments:
            arguments["path"] = os.path.relpath(arguments.pop("filePath"))
        state["metadata"] = dict(metadata=state.get("metadata", {}))
    return event


def main():
    arguments = sys.argv[1:]
    if "--version" in arguments:
        print("2.0.30")
        return 0
    profiles = Path(arguments[arguments.index("--profiles") + 1])
    if "serve" in arguments:
        print(json.dumps(dict(url="http://127.0.0.1:9")), flush=True)
        sys.stdin.read()
        return 0
    if "api" in arguments:
        print(json.dumps(dict(data=agents(profiles))))
        return 0
    assert "--server" in arguments and "--dir" not in arguments, arguments
    command = [sys.executable, str(Path(__file__).with_name("fake_live.py")), *arguments]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    sys.stderr.write(process.stderr)
    for line in process.stdout.splitlines():
        print(json.dumps(translate(json.loads(line))), flush=True)
    return process.returncode


if __name__ == "__main__":
    sys.exit(main())
