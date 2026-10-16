"""Managed UI service with cooperative worker shutdown for systemd."""

import argparse
import logging
import signal
import threading
import time
from contextlib import ExitStack
from pathlib import Path

from countersign.core.files import atomic_json
from countersign.core.runtime import run_storage
from countersign.web.config_watch import ConfigurationWatch
from countersign.web.server import make_server
from countersign.web.submissions import TaskLauncher

POLL_SECONDS = 0.2
DEFAULT_PORT = 8787
CONFIG_POLL_SECONDS = 2


class ApplicationService:
    """Stop accepting tasks before requesting a checkpoint from the active worker."""

    def __init__(self, base, port=DEFAULT_PORT, settings=None):
        base = run_storage(settings, base)
        self.launcher = TaskLauncher(base, settings)
        self.server = make_server(base, port, launcher=self.launcher)
        self.stopping = threading.Event()

    def request_stop(self, signum=None, frame=None):
        """Signal handlers only set an event; cleanup runs outside the handler."""
        self.stopping.set()

    def drain(self):
        """Let the worker use normal process cleanup and checkpoint validation."""
        child = self.launcher.process
        while child is not None and child.poll() is None:
            run = self.launcher.active_run
            if run is not None and run.is_dir():
                atomic_json(run / "stop.request", {"requested": True})
            time.sleep(POLL_SECONDS)

    def run(self):
        """Keep the main process alive until its owned worker finishes cleanup."""
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        logging.info("Countersign application: http://127.0.0.1:%s", self.server.server_port)
        watcher = ConfigurationWatch(self.launcher.settings)
        watcher.poll()
        with ExitStack() as cleanup:
            cleanup.callback(self.shutdown, thread)
            while not self.stopping.wait(CONFIG_POLL_SECONDS):
                watcher.poll()

    def shutdown(self, thread):
        """Serialize shutdown with worker creation, including in-flight HTTP requests."""
        with self.launcher.lock:
            self.launcher.stopping = True
        self.server.shutdown()
        self.drain()
        self.server.server_close()
        thread.join()


def serve(base, port=DEFAULT_PORT, settings=None):
    """Run the managed foreground process; systemd owns backgrounding and restart."""
    logging.basicConfig(level=logging.INFO)
    application = ApplicationService(base, port, settings)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, application.request_stop)
    application.run()


def main():
    """Expose a stable service command independent of the interactive CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--runs-dir", type=Path)
    args = parser.parse_args()
    serve(args.runs_dir, args.port, args.settings)


if __name__ == "__main__":
    main()
