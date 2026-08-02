"""The scheduler container has to survive its own start.

This is a subprocess test rather than a unit one because the bug it guards against only
existed outside a running event loop: ``AsyncIOScheduler.start()`` raised "no running
event loop", the container restarted forever, and every automatic lex.uz update silently
stopped happening. Importing the module or calling ``build_scheduler()`` shows nothing —
only actually running the entry point does.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_scheduler_entry_point_starts_and_keeps_running(tmp_path):
    log = tmp_path / "scheduler.log"
    env = {
        **os.environ,
        "SQLITE_PATH": str(tmp_path / "scheduler.db"),
        "ENABLE_SCHEDULER": "true",
        "PYTHONIOENCODING": "utf-8",
    }

    with log.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.app.scheduler"],
            cwd=ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if "Scheduler started" in log.read_text(encoding="utf-8", errors="replace"):
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.3)

            output = log.read_text(encoding="utf-8", errors="replace")
            assert process.poll() is None, f"process died:\n{output[-1500:]}"
            assert "Scheduler started" in output, output[-1500:]
            # the jobs are what the container exists for; a scheduler with none is idle
            assert "Added job" in output
        finally:
            process.terminate()
            process.wait(timeout=15)
