"""One opencode 1.x server per stage, so every turn of the stage runs in one process.

opencode remembers which files a session has read only inside the serving process:
separate `opencode run` processes forget them, reject an overwrite of a file read in an
earlier turn and each start cold. Turns attached to the stage's server (`run --attach`)
keep both. The server listens on loopback behind a random password and stops with the
stage. A CLI whose `run` has no `--attach` keeps one process per turn.
"""

import secrets
import subprocess
import threading

from taskrail.infrastructure import server_readiness
from taskrail.infrastructure.process_group import stop_group

ATTACH = "TASKRAIL_OPENCODE_ATTACH"
PASSWORD = "OPENCODE_SERVER_PASSWORD"
HELP_SECONDS = 30
READY_SECONDS = 120
CLOSE_SECONDS = 5
PASSWORD_BYTES = 32


def supported(command, workspace, environment):
    """Only successful help without --attach establishes an unsupported capability."""
    try:
        completed = subprocess.run(
            [*command, "run", "--help"],
            cwd=workspace,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=HELP_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Cannot probe wrapper run --help; no model session started") from error
    if completed.returncode:
        raise ValueError(
            f"Wrapper run --help failed with exit {completed.returncode}; no model session started"
        )
    return "--attach" in completed.stdout + completed.stderr


class StageServer:
    """`serve` on a loopback port for the turns of one stage; closing stops it."""

    def __init__(self, command, workspace, environment, startup=None):
        self.command = [*command, "serve", "--hostname", "127.0.0.1", "--port", "0"]
        self.workspace = workspace
        self.env = dict(environment, **{PASSWORD: secrets.token_urlsafe(PASSWORD_BYTES)})
        self.startup = dict(startup or {})
        self.startup["timeout"] = min(self.startup.get("timeout", READY_SECONDS), READY_SECONDS)
        self.process = None
        self.url = None

    def __enter__(self):
        self.process = subprocess.Popen(
            self.command,
            cwd=self.workspace,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            self.url = server_readiness.wait(self.process, self.startup)
        except BaseException:
            self.__exit__()
            raise
        threading.Thread(target=self.process.stdout.read, daemon=True).start()
        return self

    def __exit__(self, *failure):
        self.process.terminate()
        try:
            self.process.wait(CLOSE_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        stop_group(self.process.pid)
        self.process.stdout.close()

    def attachment(self):
        """What each turn needs to run on this server: its address and password."""
        return {ATTACH: self.url, PASSWORD: self.env[PASSWORD]}
