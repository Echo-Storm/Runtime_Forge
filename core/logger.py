"""
Timestamped console + file logging, ported from ALLTHERUNTIMES.ps1's
Log/Log-Status/Log-Success/Log-Skip/Log-Fail/Log-Dry functions.

Unlike the PS1 (one log file per run, kept forever minus the last 10), the
GUI also needs log lines routed to an in-app QTextEdit — callers subscribe
via add_listener() rather than the module owning any Qt objects, so this
file stays free of Qt imports.
"""

import datetime
import threading
from pathlib import Path
from typing import Callable, List


class Logger:
    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.log_file = app_dir / f"AIORuntimeInstaller_Log_{datetime.datetime.now():%Y%m%d_%H%M}.txt"
        self._listeners: List[Callable[[str], None]] = []
        # ScanWorker's parallelized version lookups are the first callers
        # that can log concurrently (each hits this on its own
        # ThreadPoolExecutor thread when an API call falls back to its
        # pinned version) — without a lock, concurrent appends to the log
        # file could interleave into a garbled line.
        self._lock = threading.Lock()
        self._prune_old_logs()

    def add_listener(self, fn: Callable[[str], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[str], None]) -> None:
        # Callers (InstallWorker, one per run) must unsubscribe when done —
        # this is a long-lived singleton, so a listener added and never
        # removed keeps firing (and keeps the dead worker object reachable)
        # for the rest of the process, one extra duplicate log line per
        # leaked listener on every subsequent run.
        with self._lock:
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

    def _emit(self, line: str) -> None:
        with self._lock:
            print(line)
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
            for fn in self._listeners:
                fn(line)

    def _log(self, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._emit(f"{ts} - {msg}")

    def status(self, msg: str) -> None:
        self._log(f"[....] {msg}")

    def success(self, msg: str) -> None:
        self._log(f"[ OK ] {msg}")

    def skip(self, msg: str) -> None:
        self._log(f"[SKIP] {msg}")

    def fail(self, msg: str) -> None:
        self._log(f"[FAIL] {msg}")

    def dry(self, msg: str) -> None:
        self._log(f"[ DRY] {msg}")

    def _prune_old_logs(self) -> None:
        """Keep only the 10 most recent run logs, same as the PS1's cleanup step."""
        try:
            logs = sorted(
                self.app_dir.glob("AIORuntimeInstaller_Log_*.txt"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for stale in logs[10:]:
                stale.unlink(missing_ok=True)
        except OSError:
            pass


_instance: Logger | None = None


def setup_logging(app_dir: Path) -> Logger:
    global _instance
    _instance = Logger(app_dir)
    return _instance


def get_logger() -> Logger:
    assert _instance is not None, "setup_logging() must be called before get_logger()"
    return _instance
