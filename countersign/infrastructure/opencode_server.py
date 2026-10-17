"""Serve the opencode 1.x CLI calls used by the workflow on top of opencode 2.x.

Usage: python -m countersign.infrastructure.opencode_server '["opencode"]' run|agent ...
Every call owns a private server; the whole tree shares the caller's process group.
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from types import MappingProxyType

from countersign.infrastructure.opencode_cli import RAW_EVENTS
from countersign.infrastructure.opencode_events import EventTranslator

READY_SECONDS = 60
POLL_SECONDS = 0.5
CLOSE_SECONDS = 5
PASSWORD_BYTES = 32
RENAMED = MappingProxyType({"shell": "bash", "subagent": "task"})
PRINT_LOGS = "--print-logs"
DIRECTORY = "--dir"
LOG_LEVEL = "--log-level"
# A stage-owned server shared by every turn of that stage.
SHARED_SERVER = "COUNTERSIGN_OPENCODE_SERVER"
PASSWORD = "OPENCODE_PASSWORD"


class Server:
    """A private 2.x server, or the stage's shared one; closing stdin ends the lease."""

    def __init__(self, command, directory, logs=False, env=None):
        self.command = command
        self.directory = directory
        self.env = dict(os.environ if env is None else env, PWD=directory)
        self.url = self.env.get(SHARED_SERVER)
        self.process = None
        if self.url:
            return
        self.env[PASSWORD] = secrets.token_urlsafe(PASSWORD_BYTES)
        self.process = subprocess.Popen(
            [*command, "serve", "--stdio", "--port", "0"],
            cwd=directory,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None if logs else subprocess.DEVNULL,
        )

    def __enter__(self):
        if self.process is not None:
            ready = json.loads(self.process.stdout.readline() or b"{}")
            threading.Thread(target=self.process.stdout.read, daemon=True).start()
            self.url = ready.get("url")
        return self

    def __exit__(self, *failure):
        if self.process is None:
            return
        self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(CLOSE_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()

    def agents(self, name=None):
        """Agent configuration loads after the server reports readiness."""
        deadline = time.monotonic() + READY_SECONDS
        while self.url and time.monotonic() < deadline:
            listed = self.request("agent.list")
            names = {agent.get("id") for agent in listed}
            if listed and (name is None or name in names):
                return listed
            time.sleep(POLL_SECONDS)
        raise RuntimeError("opencode server did not load agent {0}".format(name or "list"))

    def listing(self):
        """The 1.x `agent list` shape: a name line followed by the effective rules."""
        for agent in self.agents():
            rules = [
                dict(
                    permission=RENAMED.get(rule.get("action"), rule.get("action")),
                    pattern=rule.get("resource"),
                    action=rule.get("effect"),
                )
                for rule in agent.get("permissions", [])
            ]
            title = "{0} ({1})\n".format(agent.get("id"), agent.get("mode", "all"))
            sys.stdout.write(title)
            sys.stdout.write("  {0}\n".format(json.dumps(rules, indent=2)))

    def attachment(self):
        """Environment that lets later turns use this server instead of starting one."""
        return {SHARED_SERVER: self.url or "", PASSWORD: self.env[PASSWORD]}

    def request(self, operation):
        completed = subprocess.run(
            [*self.command, "api", "--server", self.url, operation, "--param"]
            + ["directory={0}".format(self.directory)],
            cwd=self.directory,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=READY_SECONDS,
            check=False,
        )
        return json.loads(completed.stdout or b"{}").get("data") or []


def option(arguments, name):
    """Value of a 1.x option before the message separator, if present."""
    options = arguments[: arguments.index("--")] if "--" in arguments else arguments
    return options[options.index(name) + 1] if name in options else None


def client_arguments(arguments):
    """Drop --dir (the server location is the run directory); 2.x log levels are lowercase."""
    translated, skip = [], False
    for index, argument in enumerate(arguments):
        if argument == "--":
            return translated + list(arguments[index:])
        if not skip and argument != DIRECTORY:
            level = index and arguments[index - 1] == LOG_LEVEL
            translated.append(argument.lower() if level else argument)
        skip = argument == DIRECTORY
    return translated


def relay(server, arguments):
    """Write translated events to stdout and the untouched stream to the raw file."""
    translator = EventTranslator(server.directory)
    client = subprocess.Popen(
        [*server.command, "run", "--server", server.url, *client_arguments(arguments)],
        cwd=server.directory,
        env=server.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
    )
    with open(os.environ.get(RAW_EVENTS, os.devnull), "ab") as raw:
        for line in client.stdout:
            raw.write(line)
            forward(translator.translate(line.decode("utf-8", "replace").rstrip("\n")))
    tail = translator.finish(client.wait())
    if tail:
        forward(tail)
    return client.returncode


def forward(line):
    sys.stdout.write("{0}\n".format(line))
    sys.stdout.flush()


def run(command, arguments):
    """Use the stage server when one is shared, else a private one for this turn."""
    directory = os.path.abspath(option(arguments, DIRECTORY) or os.getcwd())
    with Server(command, directory, logs=PRINT_LOGS in arguments) as server:
        server.agents(option(arguments, "--agent"))
        return relay(server, arguments)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = json.loads(argv[0])
    arguments = argv[1:]
    if arguments[:1] == ["run"]:
        return run(command, arguments[1:])
    if arguments[:2] != ["agent", "list"]:
        return subprocess.call([*command, *arguments])
    with Server(command, os.getcwd()) as server:
        server.listing()
    return 0


if __name__ == "__main__":
    sys.exit(main())
